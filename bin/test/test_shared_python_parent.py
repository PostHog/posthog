#!/usr/bin/env python3

import os
import sys
import queue
import signal
import threading
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO

import unittest

BIN = Path(__file__).resolve().parents[1]

# Each role prints its name, the pid that imported this file and its own pid.
DRIVER = f"""
import os
import sys
import signal

sys.path.insert(0, {str(BIN)!r})
import shared_python_parent

IMPORTED_BY = os.getpid()
EXITED_ONCE = os.path.join(os.getcwd(), "exited-once")


def report(name):
    print(name, IMPORTED_BY, os.getpid(), flush=True)


def stays():
    report("stays")
    signal.pause()


def exits_once():
    report("exits_once")
    if os.path.exists(EXITED_ONCE):
        signal.pause()
    open(EXITED_ONCE, "w").close()


def ignores_sigterm():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    report("ignores_sigterm")
    while True:
        signal.pause()


def fails():
    report("fails")
    sys.exit(3)


ROLES = {{"stays": stays, "exits_once": exits_once, "fails": fails, "ignores_sigterm": ignores_sigterm}}
names, min_uptime_seconds, stop_grace_seconds = sys.argv[1].split(","), float(sys.argv[2]), float(sys.argv[3])
sys.exit(
    shared_python_parent.supervise(
        {{name: ROLES[name] for name in names}},
        min_uptime_seconds,
        stop_resend_seconds=0.2,
        stop_grace_seconds=stop_grace_seconds,
    )
)
"""


class TestSharedPythonParent(unittest.TestCase):
    def setUp(self) -> None:
        self.reports: dict[int, queue.Queue[str]] = {}

    def start(self, tmp: str, roles: str, min_uptime_seconds: int, stop_grace_seconds: float = 60) -> subprocess.Popen:
        Path(tmp, "driver.py").write_text(DRIVER)
        launcher = subprocess.Popen(
            [sys.executable, "driver.py", roles, str(min_uptime_seconds), str(stop_grace_seconds)],
            cwd=tmp,
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(self.kill, launcher)
        assert launcher.stdout is not None
        lines: queue.Queue[str] = queue.Queue()
        self.reports[launcher.pid] = lines

        def collect_reports(stdout: IO[str]) -> None:
            with stdout:
                for line in stdout:
                    lines.put(line)

        threading.Thread(target=collect_reports, args=(launcher.stdout,), daemon=True).start()
        return launcher

    def kill(self, launcher: subprocess.Popen) -> None:
        try:
            os.killpg(launcher.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        launcher.wait()

    def read_report(self, launcher: subprocess.Popen) -> tuple[str, int, int]:
        try:
            line = self.reports[launcher.pid].get(timeout=30)
        except queue.Empty:
            self.fail("no role reported within 30 seconds")
        name, imported_by, pid = line.split()
        return name, int(imported_by), int(pid)

    def test_roles_fork_from_the_parent_and_a_role_that_exits_is_started_again(self) -> None:
        with TemporaryDirectory() as tmp:
            launcher = self.start(tmp, "stays,exits_once", min_uptime_seconds=0)
            reports = [self.read_report(launcher) for _ in range(3)]

            self.assertEqual(sorted(name for name, _, _ in reports), ["exits_once", "exits_once", "stays"])
            self.assertEqual({imported_by for _, imported_by, _ in reports}, {launcher.pid})
            pids = {pid for _, _, pid in reports}
            self.assertEqual(len(pids), 3)
            self.assertNotIn(launcher.pid, pids)

            launcher.terminate()
            self.assertEqual(launcher.wait(timeout=30), 0)

    def test_a_role_that_exits_right_after_its_start_stops_the_launcher_with_an_error(self) -> None:
        with TemporaryDirectory() as tmp:
            launcher = self.start(tmp, "stays,fails", min_uptime_seconds=3600)

            self.assertEqual(launcher.wait(timeout=30), 1)

    def test_a_role_that_ignores_sigterm_does_not_keep_the_launcher_alive_past_the_grace_period(self) -> None:
        with TemporaryDirectory() as tmp:
            launcher = self.start(tmp, "ignores_sigterm,stays", min_uptime_seconds=0, stop_grace_seconds=1)
            for _ in range(2):
                self.read_report(launcher)

            launcher.terminate()

            self.assertEqual(launcher.wait(timeout=30), 0)


if __name__ == "__main__":
    unittest.main()
