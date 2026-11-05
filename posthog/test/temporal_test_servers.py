"""Make the Temporal SDK download its ephemeral test servers once per run, under a deadline, before any test runs.

`WorkflowEnvironment.start_time_skipping()` and `start_local()` download their server binary on first use and reuse it
from the temp directory after that. The SDK sets no read timeout on that download, so a stalled connection hangs the
test until the job timeout. Each attempt here starts one server in a child process group that is killed at the
deadline. If every attempt fails, a test that needs that server's default download raises `TemporalServerDownloadError`,
and other tests still run.
"""

import os
import sys
import time
import random
import signal
import asyncio
import logging
import tempfile
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import NoReturn

import temporalio.service
from temporalio.testing import WorkflowEnvironment

logger = logging.getLogger(__name__)

ATTEMPTS = 3
# sdk-core waits up to 60s before it reclaims the partial download of a killed attempt, so the deadline leaves room
# for that wait plus a slow download.
ATTEMPT_TIMEOUT_SECONDS = 120
RETRY_BASE_DELAY_SECONDS = 2
# Each start method, the prefix of its download arguments, and sdk-core's file name for its default-version download.
SERVERS = {
    "start_time_skipping": ("test_server", "temporal-test-server"),
    "start_local": ("dev_server", "temporal"),
}


class TemporalServerDownloadError(RuntimeError):
    pass


def _is_downloaded(method: str) -> bool:
    # A rename in sdk-core only costs one child process per run.
    _, binary = SERVERS[method]
    return (Path(tempfile.gettempdir()) / f"{binary}-sdk-python-{temporalio.service.__version__}").is_file()


def _prepare(method: str) -> bool:
    # -P keeps posthog/test off the child's import path.
    command = [sys.executable, "-P", __file__, method]
    for attempt in range(1, ATTEMPTS + 1):
        process = subprocess.Popen(command, start_new_session=True)
        try:
            if process.wait(timeout=ATTEMPT_TIMEOUT_SECONDS) == 0:
                return True
            logger.warning("Temporal %s attempt %d exited with %d", method, attempt, process.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("Temporal %s attempt %d timed out after %ds", method, attempt, ATTEMPT_TIMEOUT_SECONDS)
        finally:
            # The group also holds any server the child started.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        if attempt < ATTEMPTS:
            delay = RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1)
            time.sleep(random.uniform(delay, 2 * delay))
    return False


def _fail_default_downloads(method: str) -> None:
    prefix, _ = SERVERS[method]
    start = getattr(WorkflowEnvironment, method)

    async def guarded(cls: type[WorkflowEnvironment], **kwargs: object) -> WorkflowEnvironment:
        downloads_default = (
            kwargs.get(f"{prefix}_existing_path") is None
            and kwargs.get(f"{prefix}_download_version", "default") == "default"
            and kwargs.get(f"{prefix}_download_ttl") is None
            and kwargs.get("download_dest_dir") is None
        )
        if downloads_default:
            raise TemporalServerDownloadError(f"Could not download the Temporal server for {method}")
        return await start(**kwargs)

    setattr(WorkflowEnvironment, method, classmethod(guarded))


def install() -> None:
    for method in SERVERS:
        if not _is_downloaded(method) and not _prepare(method):
            _fail_default_downloads(method)


def _start_once(method: str) -> NoReturn:
    async def start() -> None:
        async with await getattr(WorkflowEnvironment, method)():
            pass

    try:
        asyncio.run(start())
    except BaseException:
        logger.exception("Could not start the Temporal server for %s", method)
        os._exit(1)
    sys.stdout.flush()
    # Interpreter teardown can deadlock while it garbage-collects the SDK's Rust runtime.
    os._exit(0)


if __name__ == "__main__":
    _start_once(sys.argv[1])
