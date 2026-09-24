import os
import pty
import json
import signal
import asyncio
import termios
from contextlib import suppress

from tornado.iostream import PipeIOStream, StreamClosedError
from tornado.web import Application, RequestHandler
from tornado.websocket import WebSocketClosedError, WebSocketHandler


class HealthHandler(RequestHandler):
    def get(self) -> None:
        self.write({"status": "ok"})


class TerminalHandler(WebSocketHandler):
    stream: PipeIOStream | None = None
    pid: int | None = None
    output_task: asyncio.Task[None] | None = None
    reap_task: asyncio.Task[None] | None = None

    def check_origin(self, origin: str) -> bool:
        return origin == os.environ["TERMINAL_ORIGIN"]

    async def open(self) -> None:
        # Modal's edge supplies this header only after it verifies the connect token.
        if not self.request.headers.get("X-Verified-User-Data"):
            self.close(1008, "Authentication required")
            return
        if self.application.settings.get("terminal_connected"):
            self.close(1008, "The terminal is already connected")
            return
        self.application.settings["terminal_connected"] = True
        pid, descriptor = pty.fork()
        if pid == 0:
            os.chdir("/tmp/workspace")
            os.execve(
                "/bin/bash",
                ["bash", "--noprofile", "--norc", "-i"],
                {
                    "PATH": os.environ["PATH"],
                    "HOME": "/root",
                    "TERM": "xterm-256color",
                    "LANG": "C.UTF-8",
                    "PS1": "\\u@modal:\\w \\$ ",
                },
            )
        self.pid = pid
        self.stream = PipeIOStream(descriptor, max_buffer_size=1024 * 1024)
        self.output_task = asyncio.create_task(self._read_output())

    async def _read_output(self) -> None:
        assert self.stream is not None
        try:
            while True:
                output = await self.stream.read_bytes(65536, partial=True)
                await self.write_message(output, binary=True)
        # After the shell exits, an inline PTY read can raise EIO instead of StreamClosedError.
        except (StreamClosedError, WebSocketClosedError, OSError):
            self.close()

    async def on_message(self, message: str | bytes) -> None:
        if self.stream is None:
            return
        try:
            payload = json.loads(message)
            if isinstance(payload, str):
                await self.stream.write(payload.encode())
            elif isinstance(payload, dict):
                columns, rows = payload.get("columns"), payload.get("rows")
                if (
                    type(columns) is not int
                    or type(rows) is not int
                    or not (1 <= columns <= 1000 and 1 <= rows <= 1000)
                ):
                    raise ValueError("Invalid terminal dimensions")
                termios.tcsetwinsize(self.stream.fileno(), (rows, columns))
            else:
                raise ValueError("Invalid message")
        except (ValueError, StreamClosedError):
            self.close(1008, "Invalid terminal message")

    async def _reap_child(self, pid: int) -> None:
        with suppress(ChildProcessError):
            while os.waitpid(pid, os.WNOHANG) == (0, 0):
                await asyncio.sleep(0.05)

    def on_close(self) -> None:
        if self.output_task is not None:
            self.output_task.cancel()
        if self.stream is not None:
            self.stream.close()
        if self.pid is not None:
            with suppress(ProcessLookupError):
                os.killpg(self.pid, signal.SIGKILL)
            self.reap_task = asyncio.create_task(self._reap_child(self.pid))
            self.application.settings["terminal_connected"] = False


async def main() -> None:
    app = Application(
        [(r"/health", HealthHandler), (r"/terminal", TerminalHandler)],
        websocket_max_message_size=65536,
        websocket_ping_interval=20,
        websocket_ping_timeout=20,
        log_function=lambda _: None,
    )
    app.listen(8080, address="0.0.0.0")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
