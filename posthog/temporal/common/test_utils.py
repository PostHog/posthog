import time
import asyncio
import datetime as dt
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager

from django.db import connections

import temporalio.worker
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker


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
            self._shutdown_event.set()
            try:
                # asyncio.Event.set() from a foreign thread doesn't wake the worker's loop;
                # schedule a no-op threadsafe callback to force a wakeup so run() can return.
                loop.call_soon_threadsafe(lambda: None)
            except RuntimeError:
                pass  # loop already closed: the worker thread finished on its own
            # An abandoned worker thread can hold open database sessions (idle in transaction)
            # that block the teardown TRUNCATE of the whole test database — fail loudly instead.
            t.join(timeout=shutdown_timeout)
            if t.is_alive():
                raise RuntimeError(f"Temporal test worker thread did not shut down within {shutdown_timeout:g}s")

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
                # Join executor threads (where activity sync DB code runs) so they can't
                # outlive the worker with database work still in flight.
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                # Close this thread's Django connections; a leaked one left idle in
                # transaction blocks the teardown flush of the entire test database.
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
