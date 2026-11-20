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

from parameterized import parameterized
from test_granian_shared_socket import count_listen_sockets

LAUNCHER = Path(__file__).resolve().parents[1] / "granian_preload.py"

APP = """
import os

IMPORTED_BY = os.getpid()


def body():
    return f"{IMPORTED_BY} {os.getpid()}".encode()


def wsgi_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [body()]


async def asgi_app(scope, receive, send):
    if scope["type"] == "lifespan":
        while (await receive())["type"] != "lifespan.shutdown":
            await send({"type": "lifespan.startup.complete"})
        await send({"type": "lifespan.shutdown.complete"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body()})
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
    @parameterized.expand(
        [
            ("asgi", "false", True, 2),
            ("wsgi", "false", False, 2),
            ("asgi", "true", True, 1),
            ("wsgi", "true", False, 1),
        ]
    )
    def test_workers_share_the_parent_import_under_asgi_and_one_socket_on_request(
        self, interface: str, shared_socket: str, preloaded: bool, listen_sockets: int
    ) -> None:
        with TemporaryDirectory() as tmp:
            Path(tmp, "app.py").write_text(APP)
            port = free_port()
            env = {key: value for key, value in os.environ.items() if not key.startswith("GRANIAN_")}
            env.update(
                GRANIAN_INTERFACE=interface,
                GRANIAN_HOST="127.0.0.1",
                GRANIAN_PORT=str(port),
                GRANIAN_WORKERS="2",
                GRANIAN_WORKERS_KILL_TIMEOUT="1",
                GRANIAN_LOG_LEVEL="error",
                POSTHOG_GRANIAN_SHARED_SOCKET=shared_socket,
            )
            server = subprocess.Popen(
                [sys.executable, str(LAUNCHER), f"app:{interface}_app"], cwd=tmp, env=env, start_new_session=True
            )
            try:
                deadline = time.monotonic() + 30
                importer_by_worker: dict[int, int] = {}
                # A worker opens its own listen socket when it starts, so count the sockets only
                # after both workers have answered.
                while len(importer_by_worker) < 2:
                    if server.poll() is not None or time.monotonic() > deadline:
                        self.fail("granian did not start both workers")
                    if (body := get(port)) is None:
                        time.sleep(0.2)
                        continue
                    imported_by, served_by = (int(pid) for pid in body.split())
                    importer_by_worker[served_by] = imported_by
                self.assertNotIn(server.pid, importer_by_worker)
                self.assertEqual(
                    [imported_by == server.pid for imported_by in importer_by_worker.values()], [preloaded] * 2
                )
                self.assertEqual(count_listen_sockets(port), listen_sockets)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()


if __name__ == "__main__":
    unittest.main()
