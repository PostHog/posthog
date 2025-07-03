import asyncio
import datetime as dt
import logging
import threading
import time
from contextlib import contextmanager

import pytest
import temporalio.worker
from asgiref.sync import async_to_sync
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError
from temporalio.worker import Worker

from posthog import constants
from posthog.batch_exports.models import BatchExport
from posthog.temporal.batch_exports import ACTIVITIES, WORKFLOWS
from posthog.temporal.common.client import sync_connect


class ThreadedWorker(Worker):
    """A Temporal Worker that can run in a separate thread.

    Inteded to be used in sync tests that require a Temporal Worker.
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


@async_to_sync
async def delete_temporal_schedule(temporal: TemporalClient, schedule_id: str):
    """Delete a Temporal Schedule with the given id."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


def cleanup_temporal_schedules(temporal: TemporalClient):
    """Clean up any Temporal Schedules created during the test."""
    for schedule in BatchExport.objects.all():
        try:
            delete_temporal_schedule(temporal, str(schedule.id))
        except RPCError:
            # Assume this is fine as we are tearing down, but don't fail silently.
            logging.warn("Schedule %s has already been deleted, ignoring.", schedule.id)
            continue


@async_to_sync
async def describe_schedule(temporal: TemporalClient, schedule_id: str):
    """Return the description of a Temporal Schedule with the given id."""
    handle = temporal.get_schedule_handle(schedule_id)
    temporal_schedule = await handle.describe()
    return temporal_schedule


@async_to_sync
async def describe_workflow(temporal: TemporalClient, workflow_id: str):
    """Return the description of a Temporal Workflow with the given id."""
    handle = temporal.get_workflow_handle(workflow_id)
    temporal_workflow = await handle.describe()
    return temporal_workflow


@contextmanager
def start_test_worker(temporal: TemporalClient):
    with ThreadedWorker(
        client=temporal,
        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,  # type: ignore
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=dt.timedelta(seconds=5),
    ).run_in_thread():
        yield


@pytest.fixture
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)
