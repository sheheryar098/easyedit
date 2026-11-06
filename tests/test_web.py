"""Regression tests for the local web API."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from easyedit import web
from easyedit.util import slugify


class RevealJobTest(unittest.TestCase):
    def test_reveal_job_uses_linux_file_manager(self):
        job = Path(tempfile.mkdtemp())
        with mock.patch.object(web.os, "name", "posix"), \
                mock.patch.object(web.sys, "platform", "linux"), \
                mock.patch.object(web.shutil, "which", return_value="/usr/bin/xdg-open"), \
                mock.patch.object(web.subprocess, "Popen") as popen:
            result = web.reveal_job(job)

        self.assertEqual(result, {"ok": True})
        popen.assert_called_once_with(["/usr/bin/xdg-open", str(job)])

    def test_reveal_job_uses_macos_file_manager(self):
        job = Path(tempfile.mkdtemp())
        with mock.patch.object(web.os, "name", "posix"), \
                mock.patch.object(web.sys, "platform", "darwin"), \
                mock.patch.object(web.subprocess, "Popen") as popen:
            result = web.reveal_job(job)

        self.assertEqual(result, {"ok": True})
        popen.assert_called_once_with(["open", str(job)])

    def test_reveal_job_returns_failure_when_launcher_is_missing(self):
        job = Path(tempfile.mkdtemp())
        with mock.patch.object(web.os, "name", "posix"), \
                mock.patch.object(web.sys, "platform", "linux"), \
                mock.patch.object(web.shutil, "which", return_value=None):
            result = web.reveal_job(job)

        self.assertEqual(result, {"ok": False, "error": "no file manager found"})


class ProgressOfTest(unittest.TestCase):
    """progress_of() must not treat harmless log text as a failed run (issue #35)."""

    SKIPPED = ("[  12.3s] montage source skipped: ERROR: [youtube] dQw4w9wgxcq: "
               "Video unavailable")
    TERROR_JOB = "[   0.1s] job: /tmp/easyedit/jobs/the-terror"
    DOWNLOAD_FAILED = ("[   8.0s] download failed (Some Clip Title): "
                       "ERROR: [youtube] abcdefghijk: Video unavailable")
    DIE = "error: 'ffmpeg' not found on PATH"
    TRACEBACK = "Traceback (most recent call last):"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "run.log"

    def write(self, *lines: str) -> Path:
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.log

    def error_of(self, slug: str = "some-movie") -> str | None:
        return web.progress_of(slug, self.log)["error"]

    def test_harmless_skipped_and_terror_slug_are_not_failures(self):
        # Both issue #35 fixtures in one run.log, as specified.
        self.assertIn("error", slugify("The Terror"))
        self.write(self.TERROR_JOB, self.SKIPPED)
        self.assertIsNone(self.error_of("the-terror"))

    def test_job_path_slug_containing_error_is_ignored(self):
        self.write(self.TERROR_JOB)
        self.assertIsNone(self.error_of("the-terror"))

    def test_skipped_montage_error_line_is_ignored(self):
        self.write(self.SKIPPED)
        self.assertIsNone(self.error_of())

    def test_download_failed_error_line_is_ignored(self):
        self.write(self.DOWNLOAD_FAILED)
        self.assertIsNone(self.error_of())

    def test_raw_ytdlp_error_at_line_start_is_ignored(self):
        self.write("ERROR: [youtube] abcdefghijk: Video unavailable")
        self.assertIsNone(self.error_of())

    def test_error_substring_in_timestamped_log_is_ignored(self):
        self.write("[   1.0s] RuntimeError recovered; continuing")
        self.assertIsNone(self.error_of())

    def test_missing_or_empty_log_is_not_a_failure(self):
        self.assertFalse(self.log.exists())
        self.assertIsNone(self.error_of())
        self.log.write_text("", encoding="utf-8")
        self.assertIsNone(self.error_of())

    def test_timestamped_error_prefix_is_not_die(self):
        self.write("[   0.1s] error: this came from log(), not die()")
        self.assertIsNone(self.error_of())

    def test_traceback_is_still_reported(self):
        self.write(self.TRACEBACK, '  File "easyedit/fetch.py", line 85, in resolve',
                   "RuntimeError: boom")
        err = self.error_of()
        self.assertIsNotNone(err)
        self.assertIn("Traceback", err)

    def test_traceback_wins_over_harmless_error_text(self):
        self.write(self.TERROR_JOB, self.SKIPPED, self.TRACEBACK)
        err = self.error_of("the-terror")
        self.assertIsNotNone(err)
        self.assertIn("Traceback", err)

    def test_die_error_at_line_start_is_a_failure(self):
        self.write("", self.DIE)
        err = self.error_of()
        self.assertIsNotNone(err)
        self.assertTrue(err.startswith("error:"), err)

    def test_die_error_still_detected_after_skipped_noise(self):
        self.write(self.SKIPPED, self.DOWNLOAD_FAILED, self.DIE)
        err = self.error_of()
        self.assertEqual(err, self.DIE)

    def test_die_error_is_ignored_when_the_line_is_a_skipped_download(self):
        self.write("error: download failed (clip): network")
        self.assertIsNone(self.error_of())

    def test_nonzero_proc_exit_is_a_failure(self):
        self.write("[   0.1s] job: /tmp/easyedit/jobs/fight-club")
        proc = mock.Mock()
        proc.poll.return_value = 1
        with mock.patch.dict(web._runs, {"fight-club": {"proc": proc}}):
            err = self.error_of("fight-club")
        self.assertEqual(err, "exit 1")

    def test_running_or_successful_proc_does_not_invent_an_error(self):
        self.write(self.SKIPPED)
        running = mock.Mock()
        running.poll.return_value = None
        ok = mock.Mock()
        ok.poll.return_value = 0
        with mock.patch.dict(web._runs, {"some-movie": {"proc": running}}):
            self.assertIsNone(self.error_of())
        with mock.patch.dict(web._runs, {"some-movie": {"proc": ok}}):
            self.assertIsNone(self.error_of())


if __name__ == "__main__":
    unittest.main()
