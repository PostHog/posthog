"""Bound SDK downloads only when a test needs an ephemeral Temporal server.

Run directly with `python -m posthog.test.temporal_test_servers` to warm the cache.
"""

import os
import sys
import signal
import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from contextlib import suppress
from functools import wraps
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import pytest

    from temporalio.testing import WorkflowEnvironment

type Server = Literal["test", "dev"]


async def _start_server(server: Server) -> None:
    from temporalio.testing import WorkflowEnvironment  # noqa: PLC0415 - only the child process needs the SDK

    start = WorkflowEnvironment.start_time_skipping if server == "test" else WorkflowEnvironment.start_local
    async with await start():
        pass


async def _preparation_error(server: Server) -> subprocess.SubprocessError | TimeoutError | None:
    for attempt in range(3):
        # A process group deadline also stops blocking SDK threads and any server it spawned.
        command = [sys.executable, __file__, "--start", server]
        process = await asyncio.create_subprocess_exec(*command, start_new_session=True)
        try:
            returncode = await asyncio.wait_for(process.wait(), timeout=120)
            if returncode:
                raise subprocess.CalledProcessError(returncode, command)
            return None
        except (subprocess.CalledProcessError, TimeoutError) as error:
            if attempt == 2:
                return error
        finally:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        await asyncio.sleep(2**attempt)
    return None


# Cache failures too, so each dependent test does not repeat the retry budget.
_preparation_results: dict[Server, subprocess.SubprocessError | TimeoutError | None] = {}


async def prepare(server: Server | None = None) -> None:
    servers: tuple[Server, ...] = ("test", "dev") if server is None else (server,)
    for needed in servers:
        if needed not in _preparation_results:
            _preparation_results[needed] = await _preparation_error(needed)
        if error := _preparation_results[needed]:
            raise error


def _with_prepared_server[**P](
    start: Callable[P, Awaitable[WorkflowEnvironment]], server: Server
) -> Callable[P, Awaitable[WorkflowEnvironment]]:
    @wraps(start)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> WorkflowEnvironment:
        prefix = "test_server" if server == "test" else "dev_server"
        if (
            kwargs.get(f"{prefix}_existing_path") is None
            and kwargs.get(f"{prefix}_download_version", "default") == "default"
            and kwargs.get(f"{prefix}_download_ttl") is None
            and kwargs.get("download_dest_dir") is None
        ):
            await prepare(server)
        return await start(*args, **kwargs)

    return wrapper


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    from temporalio.testing import WorkflowEnvironment  # noqa: PLC0415 - only pytest sessions need the SDK

    _preparation_results.clear()
    monkeypatch.setattr(
        WorkflowEnvironment,
        "start_time_skipping",
        staticmethod(_with_prepared_server(WorkflowEnvironment.start_time_skipping, "test")),
    )
    monkeypatch.setattr(
        WorkflowEnvironment,
        "start_local",
        staticmethod(_with_prepared_server(WorkflowEnvironment.start_local, "dev")),
    )


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["--start", "test"]:
            asyncio.run(_start_server("test"))
        case ["--start", "dev"]:
            asyncio.run(_start_server("dev"))
        case []:
            asyncio.run(prepare())
        case _:
            raise SystemExit("usage: python -m posthog.test.temporal_test_servers")
