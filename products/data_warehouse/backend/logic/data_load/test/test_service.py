import uuid
import random
import logging
import datetime as dt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from asgiref.sync import async_to_sync, sync_to_async
from temporalio.client import (
    Client as TemporalClient,
    ScheduleActionStartWorkflow,
)
from temporalio.service import RPCError, RPCStatusCode

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.models import Organization, Team
from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.logic.data_load.service import (
    CDC_DEFAULT_INTERVAL,
    DISCOVER_SCHEMAS_INTERVAL,
    _get_cdc_extraction_schedule_id,
    _get_discover_schemas_schedule_id,
    _jitter_timedelta,
    bulk_sync_cdc_extraction_schedules,
    bulk_update_external_data_job_schedules,
    cdc_min_interval,
    get_discover_schemas_schedule,
    get_sync_schedule,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

pytestmark = [
    pytest.mark.django_db,
]


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


@pytest.fixture
def temporal():
    """Return a TemporalClient instance."""
    client = sync_connect()
    yield client
    cleanup_temporal_schedules(client)


@pytest_asyncio.fixture
async def organization():
    """A test organization."""
    name = f"TestOrg-{random.randint(1, 99999)}"
    org = await Organization.objects.acreate(name=name, is_ai_data_processing_approved=True, slug=name)

    yield org
    await org.adelete()


@pytest_asyncio.fixture
async def team(organization):
    name = f"TestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=organization, name=name)

    yield team

    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def external_data_source(team):
    source = await ExternalDataSource.objects.acreate(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Test",
        job_inputs={"test_key": "test-key"},
    )
    return source


async def _create_external_data_schema(team, external_data_source, sync_frequency_interval, sync_time_of_day):
    schema = await ExternalDataSchema.objects.acreate(
        name="TestSchema",
        team_id=team.pk,
        source_id=external_data_source.pk,
        sync_type="full_refresh",
        sync_type_config={},
        sync_frequency_interval=sync_frequency_interval,
        sync_time_of_day=sync_time_of_day,
    )
    return schema


def _get_expected_jitter(external_data_schema, sync_time):
    assert external_data_schema.sync_frequency_interval is not None
    # replicate how we define jitter in the service
    if external_data_schema.sync_frequency_interval <= dt.timedelta(hours=1):
        jitter = dt.timedelta(minutes=1)
    elif sync_time.hour != 0 or sync_time.minute != 0:
        jitter = None
    elif external_data_schema.sync_frequency_interval <= dt.timedelta(hours=12):
        jitter = dt.timedelta(minutes=30)
    else:
        jitter = dt.timedelta(hours=1)
    return jitter


def _get_expected_start_time(external_data_schema, sync_time, now):
    schedule_start = dt.datetime.combine(dt.date.today(), sync_time, tzinfo=dt.UTC)
    assert external_data_schema.sync_frequency_interval is not None
    while schedule_start < now:
        schedule_start += external_data_schema.sync_frequency_interval
    return schedule_start


@pytest.mark.parametrize(
    "sync_frequency_interval",
    [
        dt.timedelta(minutes=5),
        dt.timedelta(hours=6),
        dt.timedelta(hours=12),
        dt.timedelta(hours=24),
        dt.timedelta(days=7),
        # monthly is currently defined as 30 days
        dt.timedelta(days=30),
    ],
)
@pytest.mark.parametrize(
    "sync_time_of_day",
    [
        "00:00:00",
        "07:11:00",
        "22:59:00",
    ],
)
@pytest.mark.asyncio
async def test_get_sync_schedule(external_data_source, team, sync_frequency_interval, sync_time_of_day, temporal):
    """Test that the sync schedule is created correctly.

    We do this by creating a schedule in Temporal with the result of `get_sync_schedule` and then checking that the
    upcoming scheduled runs are correct. This is the most reliable way to test that the schedule is correct as it's not
    easy to determine based purely on the ScheduleSpec.
    """
    external_data_schema = await _create_external_data_schema(
        team=team,
        external_data_source=external_data_source,
        sync_frequency_interval=sync_frequency_interval,
        sync_time_of_day=sync_time_of_day,
    )
    assert external_data_schema.sync_frequency_interval is not None

    result = get_sync_schedule(
        external_data_schema=external_data_schema,
    )

    now = dt.datetime.now(dt.UTC)
    assert external_data_schema.sync_time_of_day is not None
    sync_time = dt.datetime.strptime(str(external_data_schema.sync_time_of_day), "%H:%M:%S").time()

    # create a schedule with the result to test that it's correct
    schedule_handle = await temporal.create_schedule(
        id=str(external_data_schema.id),
        schedule=result,
        trigger_immediately=False,
    )
    schedule_desc = await schedule_handle.describe()
    next_runs: list[dt.datetime] = schedule_desc.info.next_action_times
    assert len(next_runs) > 0

    jitter = _get_expected_jitter(external_data_schema, sync_time)
    schedule_start = _get_expected_start_time(external_data_schema, sync_time, now)
    expected_runs = [schedule_start + i * external_data_schema.sync_frequency_interval for i in range(len(next_runs))]

    # For some reason, Temporal does not always reliably schedule the first run when the interval is more than 1 day
    # so we need to handle this case separately. For example for weekly schedules it will sometimes schedule the first
    # run in 6 days time, and for monthly intervals it often schedules the first run for only 10 days in the future. We
    # don't care too much about this since we will always create the schedule using `trigger_immediately=True` and we
    # don't want the tests to be flaky, so we just check the first run is within an expected range and the interval is
    # correct.
    if external_data_schema.sync_frequency_interval > dt.timedelta(days=1):
        next_run = next_runs[0]
        assert next_run < schedule_start + external_data_schema.sync_frequency_interval
        # Check interval between runs
        for i in range(len(next_runs) - 1):
            delta = next_runs[i + 1] - next_runs[i]
            if jitter is not None:
                assert delta < external_data_schema.sync_frequency_interval + jitter
                assert delta > external_data_schema.sync_frequency_interval - jitter
            else:
                assert delta == external_data_schema.sync_frequency_interval
    else:
        # Compare actual vs expected runs
        for actual, expected in zip(next_runs, expected_runs):
            if jitter is not None:
                assert actual < expected + jitter
                assert actual > expected - jitter
            else:
                assert actual == expected


class TestDiscoverSchemasSchedule:
    @pytest.mark.asyncio
    async def test_schedule_targets_discover_schemas_workflow(self, external_data_source) -> None:
        schedule = get_discover_schemas_schedule(external_data_source)
        action = schedule.action
        assert isinstance(action, ScheduleActionStartWorkflow)
        assert action.workflow == "discover-schemas"
        assert action.id == _get_discover_schemas_schedule_id(str(external_data_source.id))
        # Inputs are passed as a single positional dict matching SyncNewSchemasActivityInputs.
        assert action.args[0] == {
            "source_id": str(external_data_source.id),
            "team_id": external_data_source.team_id,
        }
        assert schedule.spec.intervals[0].every == DISCOVER_SCHEMAS_INTERVAL


def test_jitter_timedelta():
    max_jitter = dt.timedelta(days=1)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert 0 <= hours <= 24
        if hours == 24:
            assert minutes == 0
        else:
            assert 0 <= minutes < 60

    max_jitter = dt.timedelta(hours=12)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert 0 <= hours <= 12
        if hours == 12:
            assert minutes == 0
        else:
            assert 0 <= minutes < 60

    max_jitter = dt.timedelta(hours=6)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert 0 <= hours <= 6
        if hours == 6:
            assert minutes == 0
        else:
            assert 0 <= minutes < 60

    max_jitter = dt.timedelta(hours=1)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert 0 <= hours <= 1
        if hours == 1:
            assert minutes == 0
        else:
            assert 0 <= minutes < 60

    max_jitter = dt.timedelta(minutes=30)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert hours == 0
        assert 0 <= minutes <= 30

    max_jitter = dt.timedelta(minutes=5)
    for _ in range(100):
        hours, minutes = _jitter_timedelta(max_jitter, random.Random())
        assert hours == 0
        assert 0 <= minutes <= 5


# ---------------------------------------------------------------------------
# Bulk schedule helpers — Temporal client mocked so the update/create/skip/
# failure-isolation branches are covered directly (the command tests mock these
# helpers out, so this is the only place those branches are exercised).
# ---------------------------------------------------------------------------

SERVICE = "products.data_warehouse.backend.logic.data_load.service"


def _sync_team():
    return create_team(organization=create_organization("test org"))


def _make_source(team, source_type="Postgres"):
    return ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="Completed",
        source_type=source_type,
        access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        job_inputs={},
    )


def _make_schema(team, source, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH, should_sync=True):
    return ExternalDataSchema.objects.create(
        name="TestSchema",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=sync_type,
        sync_type_config={},
        should_sync=should_sync,
        sync_frequency_interval=dt.timedelta(hours=6),
        sync_time_of_day="00:00:00",
    )


def _not_found() -> RPCError:
    return RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")


def _patch_temporal(update_side=None, create_side=None):
    """Patch the Temporal client + async schedule calls in the service module."""
    return (
        patch(f"{SERVICE}.async_connect", AsyncMock(return_value=MagicMock())),
        patch(f"{SERVICE}.a_update_schedule", AsyncMock(side_effect=update_side)),
        patch(f"{SERVICE}.a_create_schedule", AsyncMock(side_effect=create_side)),
    )


@pytest.mark.parametrize(
    "intervals,expected",
    [
        ([], CDC_DEFAULT_INTERVAL),
        ([None, None], CDC_DEFAULT_INTERVAL),
        ([dt.timedelta(hours=6)], dt.timedelta(hours=6)),
        ([dt.timedelta(hours=6), dt.timedelta(hours=1)], dt.timedelta(hours=1)),
        ([dt.timedelta(hours=6), None, dt.timedelta(hours=2)], dt.timedelta(hours=2)),
    ],
)
def test_cdc_min_interval(intervals, expected):
    assert cdc_min_interval(intervals) == expected


# --- bulk_sync_cdc_extraction_schedules (upsert: update, else create+trigger) ---


def test_bulk_sync_cdc_existing_updates_only():
    source = _make_source(_sync_team())
    conn, upd, crt = _patch_temporal()
    with conn, upd as update_mock, crt as create_mock:
        failures = bulk_sync_cdc_extraction_schedules([(source, dt.timedelta(hours=1))])

    assert failures == []
    assert update_mock.call_count == 1
    assert create_mock.call_count == 0


def test_bulk_sync_cdc_missing_creates_and_triggers():
    source = _make_source(_sync_team())
    conn, upd, crt = _patch_temporal(update_side=_not_found())
    with conn, upd, crt as create_mock:
        failures = bulk_sync_cdc_extraction_schedules([(source, dt.timedelta(hours=1))])

    assert failures == []
    assert create_mock.call_count == 1
    assert create_mock.call_args.kwargs.get("trigger_immediately") is True


def test_bulk_sync_cdc_isolates_failures_and_aligns_ids():
    team = _sync_team()
    s1, s2, s3 = _make_source(team), _make_source(team), _make_source(team)
    bad_id = _get_cdc_extraction_schedule_id(str(s2.id))

    def update_side(temporal, id, schedule, **kwargs):
        if id == bad_id:
            raise Exception("boom")

    conn, upd, crt = _patch_temporal(update_side=update_side)
    with conn, upd as update_mock, crt:
        failures = bulk_sync_cdc_extraction_schedules(
            [(s1, dt.timedelta(hours=1)), (s2, dt.timedelta(hours=1)), (s3, dt.timedelta(hours=1))]
        )

    # one failure, attributed to the right source; the other two still ran
    assert [sid for sid, _ in failures] == [str(s2.id)]
    assert isinstance(failures[0][1], Exception)
    assert update_mock.call_count == 3


def test_bulk_sync_cdc_reraises_non_not_found_rpc_errors():
    source = _make_source(_sync_team())
    other_rpc = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
    conn, upd, crt = _patch_temporal(update_side=other_rpc)
    with conn, upd, crt as create_mock:
        failures = bulk_sync_cdc_extraction_schedules([(source, dt.timedelta(hours=1))])

    # a non-NOT_FOUND error is a failure, not a silent create
    assert [sid for sid, _ in failures] == [str(source.id)]
    assert create_mock.call_count == 0


# --- bulk_update_external_data_job_schedules (update-only; missing => skipped) ---


def test_bulk_update_edj_existing_updates_only():
    team = _sync_team()
    schema = _make_schema(team, _make_source(team))
    conn, upd, crt = _patch_temporal()
    with conn, upd as update_mock, crt as create_mock:
        skipped, failures = bulk_update_external_data_job_schedules([schema])

    assert skipped == []
    assert failures == []
    assert update_mock.call_count == 1
    assert create_mock.call_count == 0  # update-only contract: never creates


def test_bulk_update_edj_missing_is_skipped_not_created():
    team = _sync_team()
    schema = _make_schema(team, _make_source(team))
    conn, upd, crt = _patch_temporal(update_side=_not_found())
    with conn, upd, crt as create_mock:
        skipped, failures = bulk_update_external_data_job_schedules([schema])

    assert skipped == [str(schema.id)]
    assert failures == []
    assert create_mock.call_count == 0


def test_bulk_update_edj_mixed_skip_fail_and_success():
    team = _sync_team()
    source = _make_source(team)
    ok, missing, broken = (_make_schema(team, source) for _ in range(3))

    def update_side(temporal, id, schedule, **kwargs):
        if id == str(missing.id):
            raise _not_found()
        if id == str(broken.id):
            raise Exception("boom")

    conn, upd, crt = _patch_temporal(update_side=update_side)
    with conn, upd as update_mock, crt as create_mock:
        skipped, failures = bulk_update_external_data_job_schedules([ok, missing, broken])

    assert skipped == [str(missing.id)]
    assert [sid for sid, _ in failures] == [str(broken.id)]
    assert create_mock.call_count == 0
    assert update_mock.call_count == 3
