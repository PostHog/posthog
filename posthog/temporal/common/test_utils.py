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
    def run_in_thread(self):
        """Run a Temporal Worker in a thread.

        Don't use this outside of tests. Once PostHog is fully async we can get rid of this.
        """
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=self.run_using_loop, daemon=True, args=(loop,))
        t.start()

        try:
            while not self.is_running:
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
