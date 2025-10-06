import logging
import datetime as dt

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from asgiref.sync import async_to_sync
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.batch_exports.service import pause_batch_export, sync_batch_export
from posthog.models import BatchExport, BatchExportDestination
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import describe_schedule, update_schedule

pytestmark = [
    pytest.mark.django_db,
]

DUMMY_CONFIG = {
    "S3": {
        "bucket_name": "my-production-s3-bucket",
        "region": "us-east-1",
        "prefix": "posthog-events/",
        "aws_access_key_id": "abc123",
        "aws_secret_access_key": "secret",
        "invalid_key": "invalid_value",
    },
    "Snowflake": {
        "account": "test-account",
        "user": "test-user",
        "database": "test-database",
        "warehouse": "test-warehouse",
        "schema": "test-schema",
    },
}


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
def team_2(organization, timezone):
    return create_team(organization=organization, timezone=timezone)


def _create_batch_export(team, destination_type, timezone):
    destination_data = {
        "type": destination_type,
        "config": DUMMY_CONFIG[destination_type],
    }

    batch_export_data = {
        "name": f"{destination_type}-batch-export",
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


@pytest.fixture
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)


def _update_schedule(temporal: TemporalClient, batch_export: BatchExport, jitter: dt.timedelta):
    schedule = describe_schedule(temporal, str(batch_export.id))
    new_schedule = schedule.schedule
    new_schedule.spec.jitter = jitter
    update_schedule(temporal, str(batch_export.id), new_schedule, keep_tz=True)
    schedule = describe_schedule(temporal, str(batch_export.id))
    assert schedule.schedule.spec.jitter == jitter


def _assert_schedule(
    temporal: TemporalClient, batch_export: BatchExport, timezone: str, jitter: dt.timedelta, paused: bool
):
    schedule = describe_schedule(temporal, str(batch_export.id))
    assert schedule.schedule.spec.time_zone_name == timezone
    assert schedule.schedule.spec.jitter == jitter
    assert schedule.schedule.state.paused == paused


@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC"],
)
@pytest.mark.parametrize("paused", (True, False))
def test_update_batch_export_schedules_for_single_batch_export(team, timezone, paused, temporal):
    """Test the update_batch_export_schedules command updates the schedule for a batch export."""

    batch_export = _create_batch_export(team, "S3", timezone)

    # Manually update the schedule so we can check that the command updates it
    _update_schedule(temporal, batch_export, dt.timedelta(hours=6))

    if paused is True:
        pause_batch_export(temporal, str(batch_export.id))

    call_command(
        "update_batch_export_schedules",
        f"--batch-export-id={batch_export.id}",
    )

    _assert_schedule(temporal, batch_export, timezone, dt.timedelta(minutes=15), paused)


def test_update_batch_export_schedules_for_all_batch_exports_of_a_given_destination_type(team, timezone, temporal):
    """Test the update_batch_export_schedules command updates the schedule for all batch exports of a given destination type."""

    batch_export_s3_1 = _create_batch_export(team, "S3", timezone)
    batch_export_s3_2 = _create_batch_export(team, "S3", timezone)
    batch_export_snowflake = _create_batch_export(team, "Snowflake", timezone)

    # Manually update the schedule so we can check that the command updates it
    _update_schedule(temporal, batch_export_s3_1, dt.timedelta(hours=6))
    _update_schedule(temporal, batch_export_s3_2, dt.timedelta(hours=6))
    _update_schedule(temporal, batch_export_snowflake, dt.timedelta(hours=6))

    call_command(
        "update_batch_export_schedules",
        f"--destination-type=S3",
    )

    # check that the S3 batch exports were updated
    _assert_schedule(temporal, batch_export_s3_1, timezone, dt.timedelta(minutes=15), False)
    _assert_schedule(temporal, batch_export_s3_2, timezone, dt.timedelta(minutes=15), False)

    # check that the Snowflake batch export was not updated
    _assert_schedule(temporal, batch_export_snowflake, timezone, dt.timedelta(hours=6), False)


def test_update_batch_export_schedules_for_all_batch_exports_of_a_given_team(team, team_2, timezone, temporal):
    """Test the update_batch_export_schedules command updates the schedule for all batch exports of a given team."""

    batch_export_1 = _create_batch_export(team, "S3", timezone)
    batch_export_2 = _create_batch_export(team, "S3", timezone)
    batch_export_team_2 = _create_batch_export(team_2, "S3", timezone)

    # Manually update the schedule so we can check that the command updates it
    _update_schedule(temporal, batch_export_1, dt.timedelta(hours=6))
    _update_schedule(temporal, batch_export_2, dt.timedelta(hours=6))
    _update_schedule(temporal, batch_export_team_2, dt.timedelta(hours=6))

    call_command(
        "update_batch_export_schedules",
        f"--team-id={team.id}",
    )

    # check that the batch exports for the given team were updated
    _assert_schedule(temporal, batch_export_1, timezone, dt.timedelta(minutes=15), False)
    _assert_schedule(temporal, batch_export_2, timezone, dt.timedelta(minutes=15), False)

    # check that the batch exports for the other team were not updated
    _assert_schedule(temporal, batch_export_team_2, timezone, dt.timedelta(hours=6), False)


def test_update_batch_export_schedules_raises_error_if_no_batch_export_id_or_destination_type_or_team_id_provided(
    team, timezone, temporal
):
    """Test the update_batch_export_schedules command raises an error if no batch export id, destination type, or team id is provided."""

    with pytest.raises(CommandError):
        call_command(
            "update_batch_export_schedules",
        )


def test_update_batch_export_schedules_raises_error_if_no_batch_exports_found(team, timezone, temporal):
    """Test the update_batch_export_schedules command raises an error if no batch exports are found."""

    batch_export_snowflake = _create_batch_export(team, "Snowflake", timezone)
    _update_schedule(temporal, batch_export_snowflake, dt.timedelta(hours=6))

    with pytest.raises(CommandError):
        call_command(
            "update_batch_export_schedules",
            f"--destination-type=S3",
        )

    # check that the Snowflake batch export was not updated
    _assert_schedule(temporal, batch_export_snowflake, timezone, dt.timedelta(hours=6), False)
