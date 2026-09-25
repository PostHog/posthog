import json
import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

from tornado.httpclient import HTTPRequest
from tornado.httputil import HTTPHeaders, HTTPServerRequest
from tornado.testing import AsyncHTTPTestCase, gen_test
from tornado.web import Application
from tornado.websocket import websocket_connect

from posthog.api.services.terminal_server import HealthHandler, TerminalHandler


class TestTerminalServer(AsyncHTTPTestCase):
    def get_app(self) -> Application:
        return Application([(r"/health", HealthHandler), (r"/terminal", TerminalHandler)])

    def setUp(self) -> None:
        super().setUp()
        self.output: asyncio.Queue[bytes] = asyncio.Queue()

        async def read_bytes(count: int, partial: bool = False) -> bytes:
            output = await self.output.get()
            assert len(output) <= count
            return output

        self.stream = MagicMock(read_bytes=AsyncMock(side_effect=read_bytes), write=AsyncMock())
        for target, value in [
            ("pty.fork", (123, 456)),
            ("PipeIOStream", self.stream),
            ("os.killpg", None),
            ("os.waitpid", (123, 0)),
        ]:
            patched = patch(f"posthog.api.services.terminal_server.{target}", return_value=value)
            patched.start()
            self.addCleanup(patched.stop)

    @gen_test
    async def test_output_waits_for_render_acknowledgments(self) -> None:
        for _ in range(4):
            self.output.put_nowait(b"x" * 65536)
        self.output.put_nowait(b"after acknowledgement")
        socket = await websocket_connect(
            HTTPRequest(self.get_url("/terminal").replace("http:", "ws:"), headers={"X-Verified-User-Data": "test"})
        )
        try:
            for _ in range(4):
                assert await socket.read_message() == b"x" * 65536
            pending = asyncio.ensure_future(socket.read_message())
            await self.http_client.fetch(self.get_url("/health"))
            assert not pending.done()
            await socket.write_message(json.dumps({"ack": 65536}))
            assert await pending == b"after acknowledgement"
            await socket.write_message(json.dumps({"ack": True}))
            assert await socket.read_message() is None
            assert socket.close_code == 1008
        finally:
            socket.close()

    @gen_test
    async def test_failed_child_launch_exits_instead_of_returning_to_the_server(self) -> None:
        for failed_operation in ("os.chdir", "os.execve"):
            with self.subTest(failed_operation=failed_operation):
                request = HTTPServerRequest(
                    connection=MagicMock(), headers=HTTPHeaders({"X-Verified-User-Data": "test"})
                )
                handler = TerminalHandler(self.get_app(), request)
                with (
                    patch("posthog.api.services.terminal_server.pty.fork", return_value=(0, 456)),
                    patch("posthog.api.services.terminal_server.Path.mkdir"),
                    patch("posthog.api.services.terminal_server.os.chdir"),
                    patch("posthog.api.services.terminal_server.os.execve"),
                    patch(
                        f"posthog.api.services.terminal_server.{failed_operation}", side_effect=OSError("launch failed")
                    ),
                    patch("posthog.api.services.terminal_server.os._exit", side_effect=SystemExit(127)),
                    self.assertRaises(SystemExit) as exited,
                ):
                    await handler.open()
                assert exited.exception.code == 127
                assert handler.stream is None
