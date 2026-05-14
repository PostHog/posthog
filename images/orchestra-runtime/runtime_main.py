"""Container entrypoint for the posthog/orchestra-runtime base image.

Reads environment, imports user modules so their @execution / @step decorators
run, then starts an orchestra Worker that polls the configured queue.

Required env:
    DATABASE_URL        Orchestra Postgres DSN reachable from inside the container
                        (use host.docker.internal:5432 on Mac/Windows or pass
                        --add-host=host.docker.internal:host-gateway on Linux).
    TASK_QUEUE          Queue this worker polls (e.g. team-1-abc123def456).
    USER_CODE_MODULES   Comma-separated dotted module paths to import. Each is
                        importable from /user-code (added to PYTHONPATH by the
                        Dockerfile).

Optional env:
    CONCURRENCY         Pollers, default 4.
    LEASE_SECONDS       Task lease, default 30.
    POLL_INTERVAL       Idle poll cadence in seconds, default 0.5.
"""

from __future__ import annotations

import os
import sys
import signal
import asyncio
import logging
import importlib

from orchestra_engine.db import Database
from orchestra_engine.worker import Worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("orchestra.runtime")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"missing required env var: {name}")
    return val


async def _main() -> None:
    dsn = _require("DATABASE_URL")
    task_queue = _require("TASK_QUEUE")
    modules_env = _require("USER_CODE_MODULES")
    concurrency = int(os.environ.get("CONCURRENCY", "4"))
    lease_seconds = int(os.environ.get("LEASE_SECONDS", "30"))
    poll_interval = float(os.environ.get("POLL_INTERVAL", "0.5"))

    modules = [m.strip() for m in modules_env.split(",") if m.strip()]
    if not modules:
        raise SystemExit("USER_CODE_MODULES must list at least one module")

    for mod in modules:
        logger.info("importing user module %s", mod)
        importlib.import_module(mod)

    db = await Database.connect(dsn)
    worker = Worker(
        db,
        task_queue=task_queue,
        concurrency=concurrency,
        lease_seconds=lease_seconds,
        poll_interval=poll_interval,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    try:
        await worker.run()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
