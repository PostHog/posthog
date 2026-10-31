"""Start each Temporal ephemeral test server once so the SDK downloads its binary into the temp directory.

CI runs this on a cache miss under a step timeout, before tests run. Tests then reuse the binary from the temp directory
and make no download request.
"""

import os
import sys
import asyncio

from temporalio.testing import WorkflowEnvironment


async def main() -> None:
    async with await WorkflowEnvironment.start_time_skipping():
        pass
    async with await WorkflowEnvironment.start_local():
        pass


if __name__ == "__main__":
    asyncio.run(main())
    sys.stdout.flush()
    # Interpreter teardown can deadlock while it garbage-collects the SDK's Rust runtime, after all work is done.
    # Exit without teardown so that the step does not wait for its timeout.
    os._exit(0)
