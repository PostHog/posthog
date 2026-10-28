"""Warm Temporal's SDK cache in a subprocess so stalled downloads can be terminated.

Run directly with `python -m posthog.test.temporal_test_servers` to warm the cache.
"""

import os
import sys
import time
import signal
import asyncio
import subprocess
from contextlib import suppress


async def _start_servers() -> None:
    from temporalio.testing import WorkflowEnvironment  # noqa: PLC0415 - only the child process needs the SDK

    async with await WorkflowEnvironment.start_time_skipping():
        pass
    async with await WorkflowEnvironment.start_local():
        pass


def prepare() -> None:
    for attempt in range(3):
        # A process group deadline also stops blocking SDK threads and any server it spawned.
        with subprocess.Popen([sys.executable, __file__, "--start"], start_new_session=True) as process:
            try:
                returncode = process.wait(timeout=120)
                if returncode:
                    raise subprocess.CalledProcessError(returncode, process.args)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 2:
                    raise
            finally:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        time.sleep(2**attempt)


if __name__ == "__main__":
    if sys.argv[1:] == ["--start"]:
        asyncio.run(_start_servers())
    else:
        prepare()
