import time
import asyncio
import datetime as dt
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager

import temporalio.worker
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker


class ThreadedWorker(Worker):
    """A Temporal Worker that can run in a separate thread.

    Intended to be used in sync tests that require a Temporal Worker.
    """

    @contextmanager
    def run_in_thread(self, *, startup_timeout: float = 30.0):
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
                if startup_error:
                    raise RuntimeError("Temporal test worker failed to start") from startup_error[0]
                if not t.is_alive():
                    raise RuntimeError("Temporal test worker thread exited before it started running")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Temporal test worker did not start within {startup_timeout:g}s")
                time.sleep(0.1)
            yield
        finally:
            self._shutdown_event.set()
            # Give the worker a chance to shut down before exiting
            max_wait = 10.0
            while t.is_alive() and max_wait > 0:
                time.sleep(0.1)
                max_wait -= 0.1

    def run_using_loop(self, loop):
        """Setup an event loop to run the Worker.

        Using async_to_sync(Worker.run) causes a deadlock.
        """
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(super().run())
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()


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
