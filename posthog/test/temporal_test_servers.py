"""Make the Temporal SDK download its ephemeral test servers once per run, under a deadline, before any test runs.

`WorkflowEnvironment.start_time_skipping()` and `start_local()` download their server binary on first use and reuse it
from the temp directory after that. The SDK sets no read timeout on that download, so a stalled connection hangs the
test until the job timeout. Each attempt here starts both servers in a child process that is killed at the deadline.
If every attempt fails, starting either environment raises `TemporalServerDownloadError`, and other tests still run.
"""

import os
import sys
import time
import asyncio
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import NoReturn

import temporalio.service
from temporalio.testing import WorkflowEnvironment

logger = logging.getLogger(__name__)

ATTEMPTS = 3
# sdk-core waits up to 60s before it reclaims the partial download of a killed attempt, so the deadline leaves room
# for that wait plus a slow download.
ATTEMPT_TIMEOUT_SECONDS = 120


class TemporalServerDownloadError(RuntimeError):
    pass


def _sdk_binaries() -> list[Path]:
    # sdk-core's names for default-version downloads. A rename only costs one child process per run.
    version = temporalio.service.__version__
    return [
        Path(tempfile.gettempdir()) / f"{name}-sdk-python-{version}" for name in ("temporal-test-server", "temporal")
    ]


def _start_each_server_once() -> None:
    async def start() -> None:
        async with await WorkflowEnvironment.start_time_skipping():
            pass
        async with await WorkflowEnvironment.start_local():
            pass

    asyncio.run(start())


def _fail_on_start(error: str) -> None:
    def start(*args: object, **kwargs: object) -> NoReturn:
        raise TemporalServerDownloadError(error)

    WorkflowEnvironment.start_time_skipping = classmethod(start)  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]
    WorkflowEnvironment.start_local = classmethod(start)  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]


def install() -> None:
    if all(binary.is_file() for binary in _sdk_binaries()):
        sys.stderr.write(f"TEMPORAL_WARMUP pid={os.getpid()} hit\n")
        return
    started = time.monotonic()
    for attempt in range(1, ATTEMPTS + 1):
        try:
            subprocess.run([sys.executable, __file__], check=True, timeout=ATTEMPT_TIMEOUT_SECONDS)
            logger.info("Prepared Temporal test servers in %.1fs", time.monotonic() - started)
            sys.stderr.write(
                f"TEMPORAL_WARMUP pid={os.getpid()} attempt={attempt} seconds={time.monotonic() - started:.1f}\n"
            )
            return
        except subprocess.SubprocessError as error:
            sys.stderr.write(f"TEMPORAL_WARMUP pid={os.getpid()} attempt={attempt} failed={error}\n")
            logger.warning("Temporal test server download attempt %d failed: %s", attempt, error)
    _fail_on_start(f"Could not download the Temporal test servers in {ATTEMPTS} attempts")


if __name__ == "__main__":
    try:
        _start_each_server_once()
    except BaseException:
        logger.exception("Could not start the Temporal test servers")
        os._exit(1)
    sys.stdout.flush()
    # Interpreter teardown can deadlock while it garbage-collects the SDK's Rust runtime.
    os._exit(0)
