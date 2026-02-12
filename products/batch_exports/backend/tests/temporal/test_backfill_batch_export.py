import uuid
import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from unittest import mock

from django.conf import settings

import temporalio
import pytest_asyncio
import temporalio.client
import temporalio.common
import temporalio.worker
import temporalio.testing
import temporalio.exceptions
from asgiref.sync import sync_to_async

from posthog.batch_exports.models import BatchExport, BatchExportBackfill, BatchExportDestination
from posthog.temporal.tests.utils.datetimes import date_range
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export,
    afetch_batch_export_backfills,
)

from products.batch_exports.backend.temporal.backfill_batch_export import (
    BackfillBatchExportInputs,
    BackfillBatchExportWorkflow,
    BackfillScheduleInputs,
    _get_backfill_info_for_events,
    backfill_range,
    backfill_schedule,
)
from products.batch_exports.backend.tests.temporal.utils.clickhouse import truncate_events


async def wait_for_workflows(
    temporal_client: temporalio.client.Client,
    schedule_id: str,
    expected_count: int,
    timeout: int = 30,
) -> list[temporalio.client.WorkflowExecution]:
    """Wait for workflows to be queryable and return them.

    Args:
        temporal_client: The Temporal client to query workflows from.
        schedule_id: The Temporal schedule ID to filter workflows.
        expected_count: The expected number of workflows to wait for.
        timeout: Maximum number of seconds to wait before raising TimeoutError.

    Returns:
        List of workflow executions matching the query.

    Raises:
        TimeoutError: If the expected number of workflows is not found within the timeout.
    """
    query = f'TemporalScheduledById="{schedule_id}" order by StartTime asc'
    workflows: list[temporalio.client.WorkflowExecution] = []
    waited = 0

    while len(workflows) < expected_count:
        waited += 1
        if waited > timeout:
            raise TimeoutError(
                f"Timed-out waiting for workflows for schedule {schedule_id} to be query-able. "
                f"Found {len(workflows)} workflows, expected {expected_count}"
            )

        await asyncio.sleep(1)
        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected_count
    return workflows


async def assert_backfill_details_in_workflow_events(
    temporal_client: temporalio.client.Client,
    workflows: list[temporalio.client.WorkflowExecution],
    expected_backfill_id: str | None = None,
    expected_start_at: str | None = None,
    expected_end_at: str | None = None,
    expected_is_earliest_backfill: bool | None = None,
) -> list[str]:
    """Assert backfill details are correctly set in workflow events.

    Checks both EVENT_TYPE_WORKFLOW_EXECUTION_STARTED (type 1) and
    EVENT_TYPE_ACTIVITY_TASK_SCHEDULED (type 10) events.

    Args:
        temporal_client: The Temporal client to get workflow handles.
        workflows: List of workflow executions to check.
        expected_backfill_id: Expected backfill ID (if None, not checked).
        expected_start_at: Expected start_at ISO string (if None, not checked).
        expected_end_at: Expected end_at ISO string (if None, not checked).
        expected_is_earliest_backfill: Expected is_earliest_backfill value (if None, not checked).

    Returns:
        List of backfill IDs found in the events.
    """
    backfill_ids = []
    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:  # EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                args = await workflow.data_converter.decode(
                    event.workflow_execution_started_event_attributes.input.payloads
                )
                backfill_details = args[0]["backfill_details"]
                if expected_backfill_id is not None:
                    assert backfill_details["backfill_id"] == expected_backfill_id
                if expected_start_at is not None:
                    assert backfill_details["start_at"] == expected_start_at
                elif "start_at" in backfill_details:
                    assert backfill_details["start_at"] is None
                if expected_end_at is not None:
                    assert backfill_details["end_at"] == expected_end_at
                elif "end_at" in backfill_details:
                    assert backfill_details["end_at"] is None
                if expected_is_earliest_backfill is not None:
                    assert backfill_details["is_earliest_backfill"] == expected_is_earliest_backfill
                backfill_ids.append(backfill_details["backfill_id"])
            elif event.event_type == 10:  # EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                args = await workflow.data_converter.decode(
                    event.activity_task_scheduled_event_attributes.input.payloads
                )
                backfill_details = args[0]["backfill_details"]
                if expected_backfill_id is not None:
                    assert backfill_details["backfill_id"] == expected_backfill_id
                if expected_start_at is not None:
                    assert backfill_details["start_at"] == expected_start_at
                elif "start_at" in backfill_details:
                    assert backfill_details["start_at"] is None
                if expected_end_at is not None:
                    assert backfill_details["end_at"] == expected_end_at
                elif "end_at" in backfill_details:
                    assert backfill_details["end_at"] is None
                if expected_is_earliest_backfill is not None:
                    assert backfill_details["is_earliest_backfill"] == expected_is_earliest_backfill
                backfill_ids.append(backfill_details["backfill_id"])

    return backfill_ids


async def assert_backfill_completed(
    batch_export_id: str | uuid.UUID,
    expected_status: str = "Completed",
) -> None:
    """Assert that a backfill was created and completed with the expected status.

    Args:
        batch_export_id: The batch export ID (UUID or string) to fetch backfills for.
        expected_status: The expected status of the backfill (default: "Completed").
    """
    backfill = await fetch_backfill(batch_export_id)
    assert backfill.status == expected_status
    assert backfill.finished_at is not None


async def fetch_backfill(batch_export_id: str | uuid.UUID) -> BatchExportBackfill:
    if isinstance(batch_export_id, str):
        batch_export_id = uuid.UUID(batch_export_id)
    backfills = await afetch_batch_export_backfills(batch_export_id=batch_export_id)
    assert len(backfills) == 1, "Expected one backfill to have been created"
    return backfills.pop()


@pytest.fixture
def timezone(request) -> ZoneInfo:
    try:
        timezone = ZoneInfo(request.param)
    except AttributeError:
        timezone = ZoneInfo("UTC")
    return timezone


@pytest.fixture
async def temporal_schedule_every_5_minutes(temporal_client, ateam):
    """Manage a test Temporal Schedule with interval 'every 5 minutes'."""
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name="no-op-export-every-5-minutes",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval="every 5 minutes",
        paused=True,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    yield handle

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
async def temporal_schedule_hourly(temporal_client, ateam):
    """Manage a test Temporal Schedule with interval 'hour'."""
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name="no-op-export-hourly",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval="hour",
        paused=True,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    yield handle

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture(
    params=[
        ("day", "UTC", None, None),
        ("day", "US/Pacific", None, None),
        ("day", "UTC", None, 1),  # 1 hour offset
        ("day", "US/Pacific", None, 2),  # 2 hour offset
        ("day", "Asia/Kathmandu", None, 3),  # 3 hour offset
        ("week", "UTC", None, None),
        ("week", "US/Pacific", None, None),
        ("week", "UTC", 0, 1),  # Sunday, 1 hour offset
        ("week", "US/Pacific", 0, 2),  # Sunday, 2 hour offset
        ("week", "Europe/Berlin", 3, 6),  # Wednesday, 6 hour offset (3 days + 6 hours = 108000 seconds)
        ("week", "Asia/Kathmandu", 3, 6),  # Wednesday, 6 hour offset (3 days + 6 hours = 108000 seconds)
    ]
)
def schedule_interval_timezone_and_offset(request):
    """Parametrized fixture for timezone, offset_day, and offset_hour combinations."""
    return request.param


@pytest.fixture
async def temporal_schedule_with_tz_and_offset(temporal_client, ateam, schedule_interval_timezone_and_offset):
    """Manage a test Temporal Schedule with parametrized interval, timezone, and offset."""
    interval, timezone, offset_day, offset_hour = schedule_interval_timezone_and_offset
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=f"no-op-export-{interval}-{timezone}-{offset_day}-{offset_hour}",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval=interval,
        paused=True,
        timezone=timezone,
        offset_day=offset_day,
        offset_hour=offset_hour,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    yield handle

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
def generate_events(clickhouse_client, ateam):
    """Factory fixture to generate test events in ClickHouse with sensible defaults.

    Returns a coroutine function that can be awaited with custom parameters.
    Defaults: table="sharded_events", end_time=start_time+1h, inserted_at=start_time.
    """

    async def _generate(
        start_time: dt.datetime,
        end_time: dt.datetime | None = None,
        inserted_at: dt.datetime | None = None,
        count: int = 10,
        event_name: str = "test-event",
        count_outside_range: int = 0,
        count_other_team: int = 0,
    ):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=start_time,
            end_time=end_time or start_time + dt.timedelta(hours=1),
            count=count,
            inserted_at=inserted_at or start_time,
            table="sharded_events",
            event_name=event_name,
            count_outside_range=count_outside_range,
            count_other_team=count_other_team,
        )

    return _generate


@pytest.mark.parametrize(
    "start_at,end_at,step,expected",
    [
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                )
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 1, 12, 20, 0, tzinfo=dt.UTC),
            dt.timedelta(hours=1),
            [
                (
                    dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(hours=12),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
            dt.datetime(2023, 1, 5, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 2, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 2, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 3, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 3, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 4, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
                (
                    dt.datetime(2023, 1, 4, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                    dt.datetime(2023, 1, 5, 6, 0, 0, tzinfo=ZoneInfo("US/Pacific")),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            None,
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.UTC),
                ),
                (
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.UTC),
                    dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            None,
            dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.timedelta(days=1),
            [
                (
                    None,
                    dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            dt.datetime(2023, 1, 15, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
            dt.timedelta(days=7),
            [
                (
                    dt.datetime(2023, 1, 1, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                    dt.datetime(2023, 1, 8, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                ),
                (
                    dt.datetime(2023, 1, 8, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                    dt.datetime(2023, 1, 15, 6, 0, 0, tzinfo=ZoneInfo("Europe/Berlin")),
                ),
            ],
        ),
    ],
)
def test_backfill_range(start_at, end_at, step, expected):
    """Test the backfill_range function yields expected ranges of dates."""
    generator = backfill_range(start_at, end_at, step)
    result = []
    for _ in range(len(expected)):
        result.append(next(generator))

    assert result == expected


async def test_backfill_schedule_activity(
    activity_environment, temporal_worker, temporal_client, temporal_schedule_hourly
):
    """Test backfill_schedule activity schedules all backfill runs."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 5, 0, 0, tzinfo=dt.UTC)
    backfill_id = str(uuid.uuid4())

    desc = await temporal_schedule_hourly.describe()
    inputs = BackfillScheduleInputs(
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=0.1,
        frequency_seconds=desc.schedule.spec.intervals[0].every.total_seconds(),
        backfill_id=backfill_id,
    )

    await activity_environment.run(backfill_schedule, inputs)

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_count=5)

    await assert_backfill_details_in_workflow_events(
        temporal_client,
        workflows,
        expected_backfill_id=backfill_id,
        expected_start_at=start_at.isoformat(),
        expected_end_at=end_at.isoformat(),
        expected_is_earliest_backfill=False,
    )


@pytest.mark.parametrize(
    "backfill_timezone",
    [
        "UTC",
        "US/Pacific",
        "Asia/Kathmandu",
    ],
)
@pytest.mark.parametrize(
    "interval,timezone,offset_day,offset_hour",
    [
        ("every 5 minutes", "UTC", None, None),  # only supports UTC and no offset
        ("hour", "UTC", None, None),  # only supports UTC and no offset
        ("day", "UTC", None, None),
        ("week", "UTC", None, None),
        ("day", "US/Pacific", None, 1),
        ("day", "Asia/Kathmandu", None, 10),
        ("week", "UTC", 0, 1),  # Sunday, 1 hour offset
        ("week", "US/Pacific", 1, 2),  # Monday, 2 hour offset
        ("week", "Asia/Kathmandu", 3, 6),  # Wednesday, 6 hour offset
    ],
)
async def test_backfill_batch_export_workflow(
    temporal_worker,
    temporal_client,
    ateam,
    generate_events,
    backfill_timezone,
    interval,
    timezone,
    offset_day,
    offset_hour,
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model.

    We test a variety of timezones and offsets to ensure that the backfill runs are executed correctly.

    Timezones come into play in two ways:
    - the batch export itself has a timezone set (this is UTC for hourly or every X minutes)
    - the start and end dates of the backfill request are timezone aware

    Note that the timezone of the team/project is not relevant.

    In this test, we want to ensure that we handle a combination of these, including where the timezones of the batch
    export and the backfill request are different.

    There are two things we can do to verify the `datetime` objects are being passed correctly:
    1. Check that the `TemporalScheduledStartTime` search attribute is set to the converted original `datetime`
    but converted to UTC timezone (Temporal works only with UTC).
    2. Check that the ID of the workflows has been set to the original `datetime` converted to UTC.

    In both cases, converting the dates back from UTC to their original timezone should yield the original
    `end_at`.

    The timezones used in this test include UTC, one timezone with fractional hour offsets (Asia/Kathmandu) and one
    other fairly common timezone (US/Pacific).
    """

    # first create a batch export with the given interval, timezone and offset
    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=f"no-op-export-{interval}-{timezone}-{offset_day}-{offset_hour}",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval=interval,
        paused=True,
        timezone=timezone,
        offset_day=offset_day,
        offset_hour=offset_hour,
    )

    expected_num_workflows = 5
    # calculate the start and end times based on the interval, timezone and offset
    # 2026-01-04 is a Sunday (offset_day=0)
    start_at = dt.datetime(2026, 1, 4, 0, 0, 0, tzinfo=ZoneInfo(timezone))
    if interval == "day" and offset_hour:
        start_at = start_at.replace(hour=offset_hour)
    elif interval == "week" and (offset_hour or offset_day):
        if offset_day:
            start_at = start_at + dt.timedelta(days=offset_day)
        if offset_hour:
            start_at = start_at.replace(hour=offset_hour)
    start_at = start_at.astimezone(ZoneInfo(backfill_timezone))

    end_at = start_at + batch_export.interval_time_delta * expected_num_workflows

    # Generate events within the backfill time range to ensure there's data to backfill
    await generate_events(
        start_time=start_at.astimezone(dt.UTC),
        end_time=end_at.astimezone(dt.UTC),
        count=100,
    )

    workflow_id = (
        f"{batch_export.id}-Backfill-{start_at.astimezone(dt.UTC).isoformat()}-{end_at.astimezone(dt.UTC).isoformat()}"
    )
    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(batch_export.id),
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=0.1,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    desc = await handle.describe()
    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    backfill = await fetch_backfill(batch_export.id)
    if backfill.status == BatchExportBackfill.Status.COMPLETED and backfill.total_records_count == 0:
        raise AssertionError("Backfill completed early with no records")

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_num_workflows, timeout=50)

    # Check that the individual workflow IDs and TemporalScheduledStartTime search attributes are set correctly.
    for index, workflow in enumerate(workflows, start=1):
        run_end_time = dt.datetime.strptime(workflow.id, f"{desc.id}-%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        expected_run_end_time = start_at + batch_export.interval_time_delta * index
        assert run_end_time == expected_run_end_time

        temporal_scheduled_start_time = workflow.search_attributes["TemporalScheduledStartTime"][0]
        assert isinstance(temporal_scheduled_start_time, dt.datetime)
        assert temporal_scheduled_start_time == expected_run_end_time

    await assert_backfill_completed(desc.id)

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)
    backfill = backfills.pop()

    await assert_backfill_details_in_workflow_events(
        temporal_client,
        workflows,
        expected_backfill_id=str(backfill.id),
        expected_start_at=start_at.isoformat(),
        expected_end_at=end_at.isoformat(),
        expected_is_earliest_backfill=False,
    )


@mock.patch("products.batch_exports.backend.temporal.backfill_batch_export.get_utcnow")
async def test_backfill_batch_export_workflow_no_end_at(
    mock_utcnow, temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam, generate_events
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""

    # Note the mocked time here, we should stop backfilling at 12 minutes and unpause the job.
    mock_utcnow.return_value = dt.datetime(2023, 1, 1, 0, 12, 12, tzinfo=dt.UTC)

    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = None
    desc = await temporal_schedule_every_5_minutes.describe()

    # Generate events within the backfill time range to ensure there's data to backfill
    await generate_events(start_time=start_at, end_time=start_at + dt.timedelta(minutes=15))

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at,
        start_delay=0.1,
    )

    batch_export = await afetch_batch_export(desc.id)
    assert batch_export.paused is True

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_count=2)

    event_backfill_ids = await assert_backfill_details_in_workflow_events(
        temporal_client,
        workflows,
        expected_start_at=start_at.isoformat(),
        expected_end_at=None,
        expected_is_earliest_backfill=False,
    )

    await assert_backfill_completed(desc.id)

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)
    backfill = backfills.pop()

    for backfill_id in event_backfill_ids:
        assert backfill_id == str(backfill.id)

    batch_export = await afetch_batch_export(desc.id)
    assert batch_export.paused is False


@pytest.mark.flaky(reruns=2)
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted(
    temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam, generate_events
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule_every_5_minutes.describe()

    # Generate events within the backfill time range to ensure there's data to backfill
    await generate_events(start_time=start_at, end_time=end_at)

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=2.0,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(seconds=20),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await temporal_schedule_every_5_minutes.delete()

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.ActivityError)
    assert isinstance(err.__cause__.__cause__, temporalio.exceptions.ApplicationError)
    assert err.__cause__.__cause__.type == "TemporalScheduleNotFoundError"


@pytest.mark.flaky(reruns=2)
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted_after_running(
    temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam, generate_events
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted.

    In this test, in contrast to the previous one, we wait until we have started running some
    backfill runs before deleting the schedule.
    """
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule_every_5_minutes.describe()

    # Generate events within the backfill time range to ensure there's data to backfill
    await generate_events(start_time=start_at, end_time=end_at)

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=2.0,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(seconds=20),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )

    # Wait for at least one workflow to start running before deleting the schedule
    await wait_for_workflows(temporal_client, desc.id, expected_count=1, timeout=10)

    await temporal_schedule_every_5_minutes.delete()

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.ActivityError)
    assert isinstance(err.__cause__.__cause__, temporalio.exceptions.ApplicationError)
    assert err.__cause__.__cause__.type == "TemporalScheduleNotFoundError"


@pytest_asyncio.fixture
async def failing_s3_batch_export(ateam, temporal_client):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "this-bucket-doesn't-exist",
            "region": "us-east-1",
            "prefix": "/",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "file_format": "invalid",
        },
    }

    failing_batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "every 5 minutes",
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        # I don't know what is mypy's problem with all these parameters.
        # The types are correct, the values are hardcoded just above.
        name=failing_batch_export_data["name"],  # type: ignore
        destination_data=failing_batch_export_data["destination"],  # type: ignore
        interval=failing_batch_export_data["interval"],  # type: ignore
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


async def test_backfill_batch_export_workflow_is_cancelled_on_repeated_failures(
    temporal_worker, failing_s3_batch_export, temporal_client, ateam, generate_events
):
    """Test BackfillBatchExportWorkflow will be cancelled on repeated failures."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    # We need some data otherwise the S3 batch export will not fail as it short-circuits.
    for d in date_range(start_at, end_at, dt.timedelta(minutes=5)):
        await generate_events(start_time=start_at, end_time=end_at, inserted_at=d)

    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(failing_s3_batch_export.id),
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=0.1,
    )

    # Need to recreate the specific ID the app would use when triggering a backfill
    start_at_str = start_at.isoformat()
    end_at_str = end_at.isoformat()
    backfill_id = f"{failing_s3_batch_export.id}-Backfill-{start_at_str}-{end_at_str}"

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=backfill_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=2),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.CancelledError), err.__cause__

    await sync_to_async(failing_s3_batch_export.refresh_from_db)()
    assert failing_s3_batch_export.paused is True

    await assert_backfill_completed(str(failing_s3_batch_export.id), expected_status="Cancelled")


async def test_backfill_batch_export_workflow_no_start_at(
    temporal_worker, temporal_schedule_hourly, temporal_client, ateam, generate_events
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""
    start_at = None
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)
    desc = await temporal_schedule_hourly.describe()

    # Generate events within the backfill time range to ensure there's data to backfill
    await generate_events(start_time=dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC), end_time=end_at)

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=desc.id,
        start_at=start_at,
        end_at=end_at.isoformat(),
        start_delay=0.1,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_count=1)

    event_backfill_ids = await assert_backfill_details_in_workflow_events(
        temporal_client,
        workflows,
        expected_start_at=None,
        expected_end_at=end_at.isoformat(),
        expected_is_earliest_backfill=True,
    )

    await assert_backfill_completed(desc.id)

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)
    backfill = backfills.pop()

    for backfill_id in event_backfill_ids:
        assert backfill_id == str(backfill.id)


@pytest_asyncio.fixture
async def events_batch_export(temporal_client, ateam, clickhouse_client):
    """Create a batch export for testing backfill info (defaults to events model)."""
    # Truncate events table to ensure clean state for each test
    await truncate_events(clickhouse_client)

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name="events-export-for-backfill-info",
        destination_data={
            "type": "S3",
            "config": {
                "bucket_name": "test-batch-exports",
                "region": "us-east-1",
                "prefix": "posthog-events/",
                "aws_access_key_id": "object_storage_root_user",
                "aws_secret_access_key": "object_storage_root_password",
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            },
        },
        interval="hour",
        paused=True,
        model="events",
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


async def run_backfill_workflow(
    temporal_client: temporalio.client.Client,
    *,
    team_id: int,
    batch_export_id: str | uuid.UUID,
    start_at: dt.datetime | None = None,
    end_at: dt.datetime | None = None,
) -> BatchExportBackfill:
    """Run a backfill workflow and return the resulting backfill model.

    Args:
        temporal_client: The Temporal client to use.
        team_id: The team ID for the backfill.
        batch_export_id: The batch export ID (string or UUID).
        start_at: Optional start datetime for the backfill.
        end_at: Optional end datetime for the backfill.

    Returns:
        The created BatchExportBackfill model after the workflow completes.
    """
    batch_export_id_str = str(batch_export_id)
    inputs = BackfillBatchExportInputs(
        team_id=team_id,
        batch_export_id=batch_export_id_str,
        start_at=start_at.isoformat() if start_at else None,
        end_at=end_at.isoformat() if end_at else None,
        start_delay=0.1,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=str(uuid.uuid4()),
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    backfills = await afetch_batch_export_backfills(batch_export_id=batch_export_id_str)
    assert len(backfills) == 1
    return backfills[0]


async def test_backfill_workflow_adjusts_start_at_when_before_earliest_data(
    temporal_worker, temporal_client, ateam, generate_events, events_batch_export
):
    """Test that backfill workflow sets adjusted_start_at when start_at is before the earliest data."""
    event_timestamp = dt.datetime(2021, 1, 2, 0, 10, 0, tzinfo=dt.UTC)
    await generate_events(start_time=event_timestamp)

    requested_start_at = dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    backfill = await run_backfill_workflow(
        temporal_client,
        team_id=events_batch_export.team_id,
        batch_export_id=events_batch_export.id,
        start_at=requested_start_at,
        end_at=dt.datetime(2021, 1, 3, 0, 0, 0, tzinfo=dt.UTC),
    )

    # Original start_at should be preserved
    assert backfill.start_at == requested_start_at
    # adjusted_start_at should be set to earliest data boundary
    assert backfill.adjusted_start_at is not None
    assert backfill.adjusted_start_at >= dt.datetime(2021, 1, 2, 0, 0, 0, tzinfo=dt.UTC)
    assert backfill.status == BatchExportBackfill.Status.COMPLETED
    assert backfill.total_records_count == 10


async def test_backfill_workflow_completes_early_when_end_at_before_earliest_data(
    temporal_worker, temporal_client, ateam, generate_events, events_batch_export
):
    """Test that backfill workflow completes early with count=0 when end_at is before earliest data."""
    event_timestamp = dt.datetime(2021, 1, 3, 0, 10, 0, tzinfo=dt.UTC)
    await generate_events(start_time=event_timestamp)

    backfill = await run_backfill_workflow(
        temporal_client,
        team_id=events_batch_export.team_id,
        batch_export_id=events_batch_export.id,
        start_at=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        end_at=dt.datetime(2021, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
    )

    assert backfill.status == BatchExportBackfill.Status.COMPLETED
    assert backfill.total_records_count == 0


async def test_backfill_workflow_completes_early_when_no_data_exists(
    temporal_worker, temporal_client, ateam, events_batch_export
):
    """Test that backfill workflow completes early with count=0 when no data exists."""
    backfill = await run_backfill_workflow(
        temporal_client,
        team_id=events_batch_export.team_id,
        batch_export_id=events_batch_export.id,
        start_at=dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        end_at=dt.datetime(2021, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
    )

    assert backfill.status == BatchExportBackfill.Status.COMPLETED
    assert backfill.total_records_count == 0


async def test_backfill_workflow_populates_estimated_record_count(
    temporal_worker, temporal_client, ateam, generate_events, events_batch_export
):
    """Test that backfill workflow populates total_records_count correctly."""
    start_at = dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2021, 1, 1, 5, 0, 0, tzinfo=dt.UTC)

    await generate_events(start_time=start_at, count=50, end_time=end_at)

    backfill = await run_backfill_workflow(
        temporal_client,
        team_id=events_batch_export.team_id,
        batch_export_id=events_batch_export.id,
        start_at=start_at,
        end_at=end_at,
    )

    assert backfill.status == BatchExportBackfill.Status.COMPLETED
    assert backfill.total_records_count == 50


class TestGetBackfillInfoForEvents:
    """Tests for the _get_backfill_info_for_events function."""

    @pytest.fixture(autouse=True)
    async def truncate_events_table(self, clickhouse_client):
        """Fixture to truncate events table before each test."""
        await truncate_events(clickhouse_client)

    @pytest.fixture
    def make_batch_export(self, ateam):
        """Factory fixture to create BatchExport objects (not saved to DB)."""

        def _make(
            interval: str = "hour",
            interval_offset: int | None = None,
            timezone: str = "UTC",
        ) -> BatchExport:
            destination = BatchExportDestination(type="S3", config={})
            return BatchExport(
                team_id=ateam.pk,
                name="Test Batch Export",
                destination=destination,
                interval=interval,
                interval_offset=interval_offset,
                timezone=timezone,
            )

        return _make

    async def test_returns_earliest_start_and_count_when_data_exists(self, ateam, generate_events, make_batch_export):
        """Test basic case: returns earliest_start and record_count when events exist."""
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=25, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        assert record_count == 25

    async def test_returns_none_and_zero_when_no_data_exists(self, ateam, make_batch_export):
        """Test that (None, 0) is returned when no events exist for the team."""
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_counts_only_events_after_start_at(self, ateam, generate_events, make_batch_export):
        """Test that count respects start_at filter."""
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include events after start_at
        assert record_count == 15

    async def test_counts_only_events_before_end_at(self, ateam, generate_events, make_batch_export):
        """Test that count respects end_at filter."""
        early_time = dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        late_time = dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC)

        await generate_events(start_time=early_time, count=10, count_other_team=10)
        await generate_events(start_time=late_time, count=15, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include events before end_at
        assert record_count == 10

    async def test_counts_only_events_in_range(self, ateam, generate_events, make_batch_export):
        """Test that count respects both start_at and end_at filters."""
        times = [
            dt.datetime(2021, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 25, 0, 0, 0, tzinfo=dt.UTC),
        ]
        counts = [5, 10, 8]

        for event_time, count in zip(times, counts):
            await generate_events(start_time=event_time, count=count, count_other_team=10)

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=dt.datetime(2021, 1, 10, 0, 0, 0, tzinfo=dt.UTC),
            end_at=dt.datetime(2021, 1, 20, 0, 0, 0, tzinfo=dt.UTC),
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        # earliest_start should be the earliest event within the date range
        assert earliest_start == dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        # count should only include the middle batch (10 events)
        assert record_count == 10

    async def test_respects_include_events_filter(self, ateam, generate_events, make_batch_export):
        """Test that include_events filter is respected."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=["pageview"],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is not None
        assert record_count == 20

    async def test_respects_exclude_events_filter(self, ateam, generate_events, make_batch_export):
        """Test that exclude_events filter is respected."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=20, count_other_team=10, event_name="pageview")
        await generate_events(start_time=event_time, count=30, count_other_team=10, event_name="click")

        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=["click"],
            filters_str="",
            extra_query_parameters={},
        )

        assert earliest_start is not None
        assert record_count == 20

    async def test_earliest_start_aligned_to_interval(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start is aligned to the interval boundary."""
        event_time = dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC)
        await generate_events(
            start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1), count_other_team=10
        )

        # Hourly interval - should align to 10:00
        batch_export = make_batch_export(interval="hour")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)

        # 5-minute interval - should align to 10:35
        batch_export = make_batch_export(interval="every 5 minutes")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC)

    async def test_custom_filters_str_is_applied(self, ateam, generate_events, make_batch_export):
        """Test that custom filters_str is included in the query."""
        event_time = dt.datetime(2021, 1, 15, 0, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=50, count_other_team=10)

        # Apply a filter that excludes all events
        batch_export = make_batch_export()
        earliest_start, record_count = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="AND 1 = 0",
            extra_query_parameters={},
        )

        assert earliest_start is None
        assert record_count == 0

    async def test_earliest_start_respects_interval_offset_daily(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects interval_offset for daily exports.

        For a daily export with offset_hour=5 (interval_offset=18000):
        - 10:30am aligns to 5am same day
        - 4:30am aligns to 5am previous day
        """
        # Event at 10:30am on Jan 15 should align to 5am Jan 15
        event_time = dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval with offset_hour=5 (18000s offset)
        batch_export = make_batch_export(interval="day", interval_offset=5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        assert earliest_start == dt.datetime(2021, 1, 15, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_interval_offset_daily_before_offset(
        self, ateam, generate_events, make_batch_export
    ):
        """Test that earliest_start correctly aligns when event is before offset hour.

        For a daily export with offset_hour=5:
        - Event at 4:30am should align to 5am the PREVIOUS day
        """
        # Event at 4:30am on Jan 15 should align to 5am Jan 14
        event_time = dt.datetime(2021, 1, 15, 4, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval with offset_hour=5 (18000s offset)
        batch_export = make_batch_export(interval="day", interval_offset=5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Event is before 5am, so it falls in the previous day's interval starting at 5am
        assert earliest_start == dt.datetime(2021, 1, 14, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_interval_offset_weekly(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects interval_offset for weekly exports.

        For a weekly export starting Monday at 5am (offset_day=1, offset_hour=5):
        - An event on Thursday at 10am should align to Monday 5am of that week
        """
        # Thursday Jan 14, 2021 at 10am (Monday was Jan 11)
        event_time = dt.datetime(2021, 1, 14, 10, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Weekly interval with offset_day=1 (Monday) and offset_hour=5
        # offset = 1 * 86400 + 5 * 3600 = 86400 + 18000 = 104400
        batch_export = make_batch_export(interval="week", interval_offset=1 * 86400 + 5 * 3600)
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Monday Jan 11, 2021 at 5am UTC
        assert earliest_start == dt.datetime(2021, 1, 11, 5, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_timezone_us_pacific(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start respects timezone for daily exports.

        For a daily export at 1am US/Pacific:
        - In January (PST = UTC-8), 1am Pacific = 9am UTC
        - An event at 10:00 UTC (2:00am PST) should align to 9:00 UTC (1:00am PST)
        - An event at 08:30 UTC (0:30am PST) should align to previous day's 9:00 UTC
        """
        # Event at 10:00 UTC on Jan 15 (which is 2:00am PST on Jan 15)
        event_time = dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval at 1am US/Pacific (offset_hour=1)
        batch_export = make_batch_export(interval="day", interval_offset=1 * 3600, timezone="US/Pacific")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # 1am PST on Jan 15 = 9am UTC on Jan 15
        assert earliest_start == dt.datetime(2021, 1, 15, 9, 0, 0, tzinfo=dt.UTC)

    async def test_earliest_start_respects_timezone_before_offset_hour(self, ateam, generate_events, make_batch_export):
        """Test that earliest_start aligns to previous day when event is before offset hour in local time.

        For a daily export at 1am US/Pacific:
        - An event at 08:30 UTC (0:30am PST) should align to previous day's 1am PST = 9am UTC
        """
        # Event at 08:30 UTC on Jan 15 (which is 0:30am PST on Jan 15, before 1am)
        event_time = dt.datetime(2021, 1, 15, 8, 30, 0, tzinfo=dt.UTC)
        await generate_events(start_time=event_time, count=5, end_time=event_time + dt.timedelta(minutes=1))

        # Daily interval at 1am US/Pacific (offset_hour=1)
        batch_export = make_batch_export(interval="day", interval_offset=1 * 3600, timezone="US/Pacific")
        earliest_start, _ = await _get_backfill_info_for_events(
            batch_export=batch_export,
            start_at=None,
            end_at=None,
            include_events=[],
            exclude_events=[],
            filters_str="",
            extra_query_parameters={},
        )
        # Event is before 1am PST, so it falls in previous day's interval
        # 1am PST on Jan 14 = 9am UTC on Jan 14
        assert earliest_start == dt.datetime(2021, 1, 14, 9, 0, 0, tzinfo=dt.UTC)
