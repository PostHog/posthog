"""Harness for booting a local MCP worker via ``wrangler dev``.

The MCP worker is a Cloudflare Worker living in ``services/mcp``. It proxies
requests to a PostHog API. For evals we run it locally via ``wrangler dev``
on a free port, pointed at a PostHog server that the developer (or CI) has
already started.

Required environment variables:

- ``POSTHOG_MCP_EVAL_API_BASE_URL`` (default ``http://localhost:8010``):
  URL where Django is reachable. Must already be running.
- ``POSTHOG_MCP_EVAL_API_KEY``: A personal API key on that PostHog instance
  with ``*`` (or sufficiently broad) scopes. Used as the bearer token.

This module starts ``wrangler dev`` once per pytest session, waits for the
``/mcp`` endpoint to become healthy, and tears it down on exit.
"""

from __future__ import annotations

import os
import time
import signal
import socket
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import IO

REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_PACKAGE_DIR = REPO_ROOT / "services" / "mcp"

DEFAULT_POSTHOG_API_BASE_URL = "http://localhost:8010"
WRANGLER_STARTUP_TIMEOUT_S = 60


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class MCPServer:
    url: str
    api_key: str
    posthog_api_base_url: str

    @property
    def auth_header(self) -> str:
        return f"Bearer {self.api_key}"


class WranglerProcess:
    """Manage a ``wrangler dev`` subprocess for the lifetime of a fixture."""

    def __init__(
        self,
        *,
        port: int,
        posthog_api_base_url: str,
        log_path: Path | None = None,
    ):
        self.port = port
        self.posthog_api_base_url = posthog_api_base_url
        self.log_path = log_path or Path("/tmp/wrangler-mcp-eval.log")
        self._process: subprocess.Popen | None = None
        self._log_handle: IO[str] | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("WranglerProcess already started")

        env = os.environ.copy()
        env["POSTHOG_API_BASE_URL"] = self.posthog_api_base_url

        self._log_handle = open(self.log_path, "w")  # noqa: SIM115
        try:
            self._process = subprocess.Popen(
                [
                    "pnpm",
                    "wrangler",
                    "dev",
                    "--port",
                    str(self.port),
                    "--ip",
                    "127.0.0.1",
                    "--local",
                ],
                cwd=str(MCP_PACKAGE_DIR),
                env=env,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            # Popen failed (e.g. pnpm not on PATH); avoid leaking the log fd.
            self._log_handle.close()
            self._log_handle = None
            raise

    def wait_ready(self, *, timeout: float = WRANGLER_STARTUP_TIMEOUT_S) -> None:
        # Probe via raw TCP rather than urllib — wrangler accepts connections
        # only once the worker is actually serving, and a bare socket avoids
        # building a URL from a runtime port (which trips static-analysis rules
        # for dynamic urllib calls).
        deadline = time.monotonic() + timeout
        last_err: OSError | None = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(f"wrangler dev exited early (see {self.log_path})")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=2):
                    return
            except OSError as e:
                last_err = e
            time.sleep(0.5)
        raise TimeoutError(
            f"wrangler dev did not become ready within {timeout}s (last error: {last_err}, see {self.log_path})"
        )

    def stop(self) -> None:
        if self._process is None:
            return
        # wrangler spawns helper processes (esbuild, miniflare workers); kill the
        # whole process group so nothing is left behind.
        try:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    self._process.kill()
                self._process.wait(timeout=5)
        finally:
            self._process = None
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None


_PORT_RETRY_ATTEMPTS = 3


def start_mcp_server() -> tuple[MCPServer, WranglerProcess]:
    api_base_url = os.environ.get("POSTHOG_MCP_EVAL_API_BASE_URL", DEFAULT_POSTHOG_API_BASE_URL)
    api_key = os.environ.get("POSTHOG_MCP_EVAL_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"POSTHOG_MCP_EVAL_API_KEY is required: a personal API key on {api_base_url} with broad scopes."
        )

    # _free_port() and wrangler's bind() are not atomic, so a concurrent process
    # can grab the port between the two. Retry a few times to absorb that race.
    last_exc: Exception | None = None
    for _ in range(_PORT_RETRY_ATTEMPTS):
        port = _free_port()
        process = WranglerProcess(port=port, posthog_api_base_url=api_base_url)
        process.start()
        try:
            process.wait_ready()
        except Exception as exc:
            last_exc = exc
            process.stop()
            continue
        return MCPServer(
            url=f"http://127.0.0.1:{port}/mcp",
            api_key=api_key,
            posthog_api_base_url=api_base_url,
        ), process

    raise RuntimeError(f"wrangler dev failed to start after {_PORT_RETRY_ATTEMPTS} attempts: {last_exc}")
