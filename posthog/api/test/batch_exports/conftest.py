import asyncio
from contextlib import contextmanager
import datetime as dt
import logging
import threading
import time
from asgiref.sync import async_to_sync
import pytest

from temporalio.service import RPCError
from temporalio.client import Client as TemporalClient

from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from django.conf import settings
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
from temporalio.api.workflowservice.v1 import GetSearchAttributesRequest
from posthog.batch_exports.models import BatchExport


from posthog.temporal.client import sync_connect
from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS


class ThreadedWorker(Worker):
    """A Temporal Worker that can run in a separate thread.

    Inteded to be used in sync tests that require a Temporal Worker.
    """

    @contextmanager
    def run_in_thread(self):
        """Run a Temporal Worker in a thread.

        Don't use this outside of tests. Once PostHog is fully we can get rid of this.
        """
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=self.run, daemon=True, args=(loop,))
        t.start()

        try:
            while not self.is_running:
                time.sleep(0.1)
            yield
        finally:
            self._shutdown_event.set()

    def run(self, loop):
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
async def get_search_attributes(client: TemporalClient, request):
    """Wrapper for workflow_service.get_search_attributes.

    This function is but async_to_sync fails to recognize it as such and fails on a type check.
    So, we wrap it in our own function to pass that to async_to_sync.
    """
    return await client.workflow_service.get_search_attributes(request)


@async_to_sync
async def add_search_attributes(client: TemporalClient, request):
    """Wrapper for workflow_service.add_search_attributes.

    This function is but async_to_sync fails to recognize it as such and fails on a type check.
    So, we wrap it in our own function to pass that to async_to_sync.
    """
    return await client.operator_service.add_search_attributes(request)


def ensure_search_attributes(temporal: TemporalClient):
    """Ensure custom search attributes are present adding them if not."""
    resp = get_search_attributes(temporal, GetSearchAttributesRequest())
    custom_search_attributes = {
        "DestinationId": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "DestinationType": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "TeamId": IndexedValueType.INDEXED_VALUE_TYPE_INT,
        "TeamName": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "BatchExportId": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
    }
    are_present = all(k in resp.keys.keys() for k in custom_search_attributes.keys())

    if are_present:
        return

    request = AddSearchAttributesRequest(search_attributes=custom_search_attributes)
    add_search_attributes(temporal, request)
    resp = get_search_attributes(temporal, GetSearchAttributesRequest())
    custom_search_attributes = {
        "DestinationId": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "DestinationType": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "TeamId": IndexedValueType.INDEXED_VALUE_TYPE_INT,
        "TeamName": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
        "BatchExportId": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
    }

    are_present = all(k in resp.keys.keys() for k in custom_search_attributes.keys())

    assert are_present is True


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
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=dt.timedelta(seconds=5),
    ).run_in_thread():
        ensure_search_attributes(temporal)
        yield


@pytest.fixture(autouse=True)
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)
