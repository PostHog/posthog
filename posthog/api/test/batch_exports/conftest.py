import logging

import pytest

from asgiref.sync import async_to_sync
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.api.test.batch_exports.fixtures import create_organization, create_team, create_user
from posthog.api.test.batch_exports.operations import start_test_worker
from posthog.batch_exports.models import BatchExport
from posthog.temporal.common.client import sync_connect


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


@pytest.fixture(scope="module")
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client


@pytest.fixture(scope="module", autouse=True)
def temporal_worker(temporal):
    """Use a module scoped fixture to start a Temporal Worker.

    This saves a lot of time, as waiting for the worker to stop takes a while.
    """
    with start_test_worker(temporal):
        yield


@pytest.fixture(autouse=True)
def cleanup(temporal):
    cleanup_temporal_schedules(temporal)


@pytest.fixture
def organization():
    return create_organization("Test Org")


@pytest.fixture
def team(organization):
    return create_team(organization)


@pytest.fixture
def user(organization):
    return create_user("test@user.com", "Test User", organization)
