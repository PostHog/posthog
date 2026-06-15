import sys
import time
import asyncio
import logging
import datetime as dt
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager

from django.db import connections

import temporalio.worker
from asgiref.sync import sync_to_async
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


class ThreadedWorker(Worker):
    """A Temporal Worker that can run in a separate thread.

    Intended to be used in sync tests that require a Temporal Worker.
    """

    @contextmanager
    def run_in_thread(self, *, startup_timeout: float = 30.0, shutdown_timeout: float = 60.0):
        """Run a Temporal Worker in a thread.

        Don't use this outside of tests. Once PostHog is fully async we can get rid of this.
        """
        loop = asyncio.new_event_loop()
        startup_error: list[Exception] = []

        def run() -> None:
            try:
                self.run_using_loop(loop)
            except Exception as e:
                # Capture so the main thread can fail fast on a startup crash, and re-raise so a
                # worker that dies *after* startup still surfaces its traceback (threading.excepthook).
                startup_error.append(e)
                raise

        t = threading.Thread(target=run, daemon=True)
        t.start()

        try:
            # Bound the wait for the worker to come up. If the worker thread dies or
            # never reports running, fail fast with a clear error — a silent spin here
            # would otherwise consume the entire CI job timeout.
            deadline = time.monotonic() + startup_timeout
            while not self.is_running:
                if not t.is_alive() or startup_error:
                    # A crashing worker appends to startup_error before its thread exits, so
                    # surface that cause rather than a bare "exited before it started" message.
                    if startup_error:
                        raise RuntimeError("Temporal test worker failed to start") from startup_error[0]
                    raise RuntimeError("Temporal test worker thread exited before it started running")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Temporal test worker did not start within {startup_timeout:g}s")
                time.sleep(0.1)
            yield
        finally:
            try:
                # asyncio primitives aren't thread-safe: set() can raise if the worker crashed
                # and closed its loop, and the no-op callback forces a loop wakeup so run()
                # observes the event (a cross-thread set() alone doesn't wake the selector).
                self._shutdown_event.set()
                loop.call_soon_threadsafe(lambda: None)
            except RuntimeError:
                pass  # loop already closed: the worker thread finished (or crashed) on its own
            # An abandoned worker thread can hold open database sessions (idle in transaction)
            # that block the teardown TRUNCATE of the whole test database — fail loudly instead.
            t.join(timeout=shutdown_timeout)
            if t.is_alive():
                message = f"Temporal test worker thread did not shut down within {shutdown_timeout:g}s"
                if sys.exc_info()[0] is not None:
                    # Raising here would replace the in-flight exception (the likely root
                    # cause of the wedged worker) — report instead of masking it.
                    logger.error(message)
                else:
                    raise RuntimeError(message)

    def run_using_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Setup an event loop to run the Worker.

        Using async_to_sync(Worker.run) causes a deadlock.
        """
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(super().run())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
                # Join the loop's default executor (asyncio.to_thread file/network work),
                # bounded: a thread wedged on an uncancellable call must not hang shutdown.
                # type-ignore: typeshed's AbstractEventLoop lacks the timeout param that
                # the concrete BaseEventLoop has since Python 3.12.
                loop.run_until_complete(loop.shutdown_default_executor(timeout=10))  # type: ignore[call-arg]
                # Activity ORM code runs via thread-sensitive sync_to_async on asgiref's
                # long-lived global executor thread; hop onto that same thread to close its
                # Django connections — a session leaked idle-in-transaction there blocks
                # the teardown TRUNCATE of the whole test database.
                loop.run_until_complete(asyncio.wait_for(sync_to_async(connections.close_all)(), timeout=10))
            except (TimeoutError, RuntimeError):
                logger.exception("Could not fully clean up Temporal test worker executors/connections")
            finally:
                loop.close()
                connections.close_all()


@contextmanager
def start_test_worker(
    temporal: TemporalClient,
    *,
    task_queue: str,
    workflows: Sequence[type],
    activities: Sequence[Callable],
):
    with ThreadedWorker(
        client=temporal,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=dt.timedelta(seconds=5),
    ).run_in_thread():
        yield
