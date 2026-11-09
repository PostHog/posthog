#!/usr/bin/env python3

import os
import sys
import time
import signal
import socket
import subprocess
import http.client
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest

LAUNCHER = Path(__file__).resolve().parents[1] / "granian_preload.py"

APP = """
import os

IMPORTED_BY = os.getpid()


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [f"{IMPORTED_BY} {os.getpid()}".encode()]
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(port: int) -> str | None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        return conn.getresponse().read().decode()
    except OSError:
        return None
    finally:
        conn.close()


@unittest.skipUnless(sys.platform == "linux", "hobby runs granian on Linux")
class TestGranianPreload(unittest.TestCase):
    def test_workers_run_the_app_the_parent_imported(self) -> None:
        with TemporaryDirectory() as tmp:
            Path(tmp, "app.py").write_text(APP)
            port = free_port()
            env = {key: value for key, value in os.environ.items() if not key.startswith("GRANIAN_")}
            env.update(
                GRANIAN_INTERFACE="wsgi",
                GRANIAN_HOST="127.0.0.1",
                GRANIAN_PORT=str(port),
                GRANIAN_WORKERS="2",
                GRANIAN_WORKERS_KILL_TIMEOUT="1",
                GRANIAN_LOG_LEVEL="error",
            )
            server = subprocess.Popen(
                [sys.executable, str(LAUNCHER), "app:app"], cwd=tmp, env=env, start_new_session=True
            )
            try:
                deadline = time.monotonic() + 30
                while (body := get(port)) is None:
                    if server.poll() is not None or time.monotonic() > deadline:
                        self.fail("granian did not start")
                    time.sleep(0.2)
                imported_by, served_by = (int(pid) for pid in body.split())
                self.assertEqual(imported_by, server.pid)
                self.assertNotEqual(served_by, server.pid)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == "__main__":
    unittest.main()
