import datetime as dt
import logging

import pytest
from asgiref.sync import async_to_sync
from django.core.management import call_command
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.batch_exports.service import pause_batch_export, sync_batch_export
from posthog.models import BatchExport, BatchExportDestination
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import update_schedule

pytestmark = [
    pytest.mark.django_db,
]


@pytest.fixture
def timezone(request):
    try:
        return request.param
    except AttributeError:
        return "UTC"


@pytest.fixture
def organization():
    return create_organization("test")


@pytest.fixture
def team(organization, timezone):
    return create_team(organization=organization, timezone=timezone)


@pytest.fixture
def batch_export(team):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
            "invalid_key": "invalid_value",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "interval": "hour",
    }

    destination = BatchExportDestination(**destination_data)
    batch_export = BatchExport(team=team, destination=destination, **batch_export_data)

    sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()
    return batch_export


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


@pytest.fixture
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC"],
)
@pytest.mark.parametrize("paused", (True, False))
def test_update_batch_export_schedules(timezone, paused, batch_export, temporal):
    """Test the update_batch_export_schedules command updates the schedule for a batch export."""

    # Manually update the schedule so we can check that the command updates it
    schedule = describe_schedule(temporal, str(batch_export.id))
    new_schedule = schedule.schedule
    new_schedule.spec.jitter = dt.timedelta(hours=6)
    update_schedule(temporal, str(batch_export.id), new_schedule, keep_tz=True)
    schedule = describe_schedule(temporal, str(batch_export.id))
    assert schedule.schedule.spec.jitter == dt.timedelta(hours=6)

    if paused is True:
        pause_batch_export(temporal, str(batch_export.id))

    call_command(
        "update_batch_export_schedules",
        f"--batch-export-id={batch_export.id}",
    )

    # Check that the schedule was updated
    schedule = describe_schedule(temporal, str(batch_export.id))
    assert schedule.schedule.spec.time_zone_name == timezone
    # Check that the jitter was reset
    assert schedule.schedule.spec.jitter == dt.timedelta(minutes=15)
    # Ensure the schedule state was preserved
    assert schedule.schedule.state.paused == paused
