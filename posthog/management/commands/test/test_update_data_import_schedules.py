import logging
import datetime as dt

import pytest

from django.core.management import CommandError, call_command

from asgiref.sync import async_to_sync
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.management.commands.update_data_import_schedules import _get_external_data_schemas
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import describe_schedule, update_schedule
from posthog.warehouse.data_load.service import sync_external_data_job_workflow
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def organization():
    return create_organization("test org")


@pytest.fixture
def team(organization):
    return create_team(organization=organization)


@pytest.fixture
def team_2(organization):
    return create_team(organization=organization)


def _create_external_data_source(team, source_type):
    return ExternalDataSource.objects.create(team=team, source_type=source_type, job_inputs={})


def _create_external_data_schema(
    external_data_source,
    sync_frequency_interval,
    sync_time_of_day,
    should_sync=True,
    updated_at=None,
    create_schedule=True,
    sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
):
    external_data_schema = ExternalDataSchema.objects.create(
        name="TestSchema",
        team=external_data_source.team,
        source=external_data_source,
        should_sync=should_sync,
        sync_type=sync_type,
        sync_frequency_interval=sync_frequency_interval,
        sync_time_of_day=sync_time_of_day,
    )
    if create_schedule:
        # create the schedule in Temporal
        sync_external_data_job_workflow(external_data_schema, create=True, should_sync=should_sync)
    # simulate the updated_at field being set to a different value
    if updated_at:
        ExternalDataSchema.objects.filter(id=external_data_schema.id).update(updated_at=updated_at)
    return external_data_schema


@async_to_sync
async def delete_temporal_schedule(temporal: TemporalClient, schedule_id: str):
    """Delete a Temporal Schedule with the given id."""
    handle = temporal.get_schedule_handle(schedule_id)
    await handle.delete()


def cleanup_temporal_schedules(client):
    """Clean up any Temporal Schedules created during the test."""
    for schedule in ExternalDataSchema.objects.all():
        try:
            delete_temporal_schedule(client, str(schedule.id))
        except RPCError:
            # Assume this is fine as we are tearing down, but don't fail silently.
            logging.warning("Schedule %s has already been deleted, ignoring.", schedule.id)
            continue


@pytest.fixture(autouse=True)
def temporal():
    """Return a TemporalClient instance and cleanup any schedules created during the test."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)


def _assert_schedule(temporal: TemporalClient, external_data_schema: ExternalDataSchema, paused: bool | None = None):
    schedule = describe_schedule(temporal, str(external_data_schema.id))
    if paused is not None:
        assert schedule.schedule.state.paused == paused
    else:
        assert schedule.schedule.state.paused != external_data_schema.should_sync


def _update_schedule(temporal: TemporalClient, external_data_schema: ExternalDataSchema, paused: bool):
    schedule = describe_schedule(temporal, str(external_data_schema.id))
    new_schedule = schedule.schedule
    new_schedule.state.paused = paused
    update_schedule(temporal, str(external_data_schema.id), new_schedule)
    schedule = describe_schedule(temporal, str(external_data_schema.id))
    assert schedule.schedule.state.paused == paused


def test_command_updates_all_schedules_for_a_given_source(team, temporal):
    source = _create_external_data_source(team, "Stripe")
    # create a couple of schemas for the source (to ensure that the command updates all schemas for the source)
    external_data_schema_1 = _create_external_data_schema(source, dt.timedelta(hours=6), "00:00:00", should_sync=True)
    external_data_schema_2 = _create_external_data_schema(source, dt.timedelta(hours=1), "00:00:00", should_sync=True)
    # assert that the schedules are created in Temporal
    _assert_schedule(temporal, external_data_schema_1)
    _assert_schedule(temporal, external_data_schema_2)

    # create another source with another schema to ensure that the command only updates the correct source
    source_2 = _create_external_data_source(team, "BigQuery")
    external_data_schema_3 = _create_external_data_schema(source_2, dt.timedelta(hours=6), "00:00:00", should_sync=True)
    _assert_schedule(temporal, external_data_schema_3)

    # Manually update the schedules so we can check that the command updates (or doesn't update) them
    _update_schedule(temporal, external_data_schema_1, paused=True)
    _update_schedule(temporal, external_data_schema_2, paused=True)
    _update_schedule(temporal, external_data_schema_3, paused=True)

    call_command(
        "update_data_import_schedules",
        f"--external-data-source-id={source.id}",
    )

    _assert_schedule(temporal, external_data_schema_1)
    _assert_schedule(temporal, external_data_schema_2)
    # this one should still be paused
    _assert_schedule(temporal, external_data_schema_3, paused=True)


def test_command_updates_all_schedules_for_a_given_source_since_a_given_updated_at(team, temporal):
    source = _create_external_data_source(team, "Stripe")
    # create a couple of schemas for the source (to ensure that the command updates all schemas for the source)
    external_data_schema_1 = _create_external_data_schema(source, dt.timedelta(hours=6), "00:00:00", should_sync=True)
    external_data_schema_2 = _create_external_data_schema(
        source, dt.timedelta(hours=1), "00:00:00", updated_at=dt.datetime(2020, 1, 1), should_sync=True
    )
    # assert that the schedules are created in Temporal
    _assert_schedule(temporal, external_data_schema_1)
    _assert_schedule(temporal, external_data_schema_2)

    # Manually update the schedules so we can check that the command updates (or doesn't update) them
    _update_schedule(temporal, external_data_schema_1, paused=True)
    _update_schedule(temporal, external_data_schema_2, paused=True)

    call_command(
        "update_data_import_schedules",
        f"--external-data-source-id={source.id}",
        f"--updated-at-gt=2020-01-02",
    )

    _assert_schedule(temporal, external_data_schema_1)
    # this one should still be paused
    _assert_schedule(temporal, external_data_schema_2, paused=True)


def test_get_external_data_schemas(
    team,
    team_2,
):
    """Tests the filtering logic of the command.

    The above tests ensure that the command updates the schedules correctly, so here we just test that the filtering
    logic works for various cases.
    """
    # create several different external data sources and schemas with different properties
    stripe_source = _create_external_data_source(team, "Stripe")
    bigquery_source = _create_external_data_source(team, "BigQuery")
    stripe_source_team_2 = _create_external_data_source(team_2, "Stripe")

    # create a couple of schemas for the source (to ensure that the command updates all schemas for the source)
    stripe_schema_1 = _create_external_data_schema(
        stripe_source, dt.timedelta(hours=6), "00:00:00", should_sync=True, create_schedule=False
    )
    stripe_schema_2 = _create_external_data_schema(
        stripe_source, dt.timedelta(hours=1), "00:00:00", should_sync=True, create_schedule=False
    )
    bigquery_schema_paused = _create_external_data_schema(
        bigquery_source, dt.timedelta(hours=6), "00:00:00", should_sync=False, create_schedule=False
    )
    bigquery_schema_incremental = _create_external_data_schema(
        bigquery_source,
        dt.timedelta(hours=1),
        "00:00:00",
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        create_schedule=False,
    )
    stripe_schema_team_2 = _create_external_data_schema(
        stripe_source_team_2,
        dt.timedelta(hours=24),
        "00:00:00",
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        create_schedule=False,
    )
    old_stripe_schema = _create_external_data_schema(
        stripe_source,
        dt.timedelta(hours=12),
        "00:00:00",
        should_sync=True,
        updated_at=dt.datetime(2020, 1, 1),
        create_schedule=False,
    )

    # test using external_data_source_id
    schemas = _get_external_data_schemas(external_data_source_id=stripe_source.id)
    assert len(schemas) == 3
    assert stripe_schema_1 in schemas
    assert stripe_schema_2 in schemas
    assert old_stripe_schema in schemas

    # test using team_ids
    schemas = _get_external_data_schemas(team_ids=f"{team.id},{team_2.id}")
    assert len(schemas) == 6
    schemas = _get_external_data_schemas(team_ids=f"{team_2.id}")
    assert len(schemas) == 1
    assert stripe_schema_team_2 in schemas

    # test using exclude_team_ids
    schemas = _get_external_data_schemas(exclude_team_ids=f"{team.id}")
    assert len(schemas) == 1
    assert stripe_schema_team_2 in schemas

    # test using source_type
    schemas = _get_external_data_schemas(source_type="Stripe")
    assert len(schemas) == 4
    assert stripe_schema_1 in schemas
    assert stripe_schema_2 in schemas
    assert stripe_schema_team_2 in schemas
    assert old_stripe_schema in schemas

    # test using sync_type
    schemas = _get_external_data_schemas(sync_type=ExternalDataSchema.SyncType.INCREMENTAL)
    assert len(schemas) == 2
    assert bigquery_schema_incremental in schemas
    assert stripe_schema_team_2 in schemas

    # test using sync_frequency
    schemas = _get_external_data_schemas(sync_frequency="1hour")
    assert len(schemas) == 2
    assert stripe_schema_2 in schemas
    assert bigquery_schema_incremental in schemas

    # test using should_sync
    schemas = _get_external_data_schemas(should_sync=False)
    assert len(schemas) == 1
    assert bigquery_schema_paused in schemas

    # test using updated_at_gt
    schemas = _get_external_data_schemas(updated_at_gt="2020-01-02")
    assert len(schemas) == 5
    assert old_stripe_schema not in schemas

    # test using updated_at_lt
    schemas = _get_external_data_schemas(updated_at_lt="2020-01-02")
    assert len(schemas) == 1
    assert old_stripe_schema in schemas

    # test using a combination of filters
    schemas = _get_external_data_schemas(
        exclude_team_ids=f"{team.id}",
        source_type="Stripe",
    )
    assert len(schemas) == 1
    assert stripe_schema_team_2 in schemas


def test_update_data_import_schedules_raises_error_if_no_args():
    """Test that the command raises an error if no arguments are provided.

    This is more of a safety net than anything else, so could remove in future if we want to.
    """
    with pytest.raises(CommandError, match="Must call this command with at least one filter"):
        call_command("update_data_import_schedules")


def test_update_data_import_schedules_raises_error_if_no_schemas_found(team):
    source = _create_external_data_source(team, "Stripe")
    _create_external_data_schema(source, dt.timedelta(hours=6), "00:00:00", should_sync=True)
    with pytest.raises(CommandError, match="No external data schemas found"):
        call_command(
            "update_data_import_schedules",
            f"--source-type=NonExistentType",
        )


def test_update_data_import_schedules_raises_error_if_team_ids_and_exclude_team_ids_overlap(team):
    """Test that the command raises an error if team_ids and exclude_team_ids overlap."""
    with pytest.raises(CommandError, match=f"Team IDs {team.id} present in both include and exclude lists"):
        call_command(
            "update_data_import_schedules",
            f"--team-ids={team.id}",
            f"--exclude-team-ids={team.id}",
        )
