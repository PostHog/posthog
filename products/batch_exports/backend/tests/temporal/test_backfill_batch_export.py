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
    backfill_range,
    backfill_schedule,
    get_batch_export_interval,
)

pytestmark = [pytest.mark.django_db(transaction=True)]


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
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

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
    if isinstance(batch_export_id, str):
        batch_export_id = uuid.UUID(batch_export_id)
    backfills = await afetch_batch_export_backfills(batch_export_id=batch_export_id)
    assert len(backfills) == 1, "Expected one backfill to have been created"
    backfill = backfills.pop()
    assert backfill.status == expected_status
    assert backfill.finished_at is not None


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


async def test_get_batch_export_interval_every_5_minutes_schedule(
    activity_environment, temporal_worker, temporal_schedule_every_5_minutes
):
    """Test get_batch_export_interval returns the correct interval."""
    desc = await temporal_schedule_every_5_minutes.describe()
    expected = desc.schedule.spec.intervals[0].every.total_seconds()

    result = await activity_environment.run(get_batch_export_interval, desc.id)

    assert result == expected == 5 * 60


async def test_get_batch_export_interval_hourly_schedule(
    activity_environment, temporal_worker, temporal_schedule_hourly
):
    """Test get_batch_export_interval returns correct interval for hourly schedule."""
    desc = await temporal_schedule_hourly.describe()
    expected = desc.schedule.spec.intervals[0].every.total_seconds()

    result = await activity_environment.run(get_batch_export_interval, desc.id)

    assert result == expected == 3600


async def test_get_batch_export_interval_with_tz_and_offset(
    activity_environment, temporal_worker, temporal_schedule_with_tz_and_offset, schedule_interval_timezone_and_offset
):
    """Test get_batch_export_interval returns correct interval for with timezone and offset."""
    desc = await temporal_schedule_with_tz_and_offset.describe()
    interval, _, _, _ = schedule_interval_timezone_and_offset
    if interval == "day":
        expected = 24 * 60 * 60
    elif interval == "week":
        expected = 7 * 24 * 3600

    result = await activity_environment.run(get_batch_export_interval, desc.id)

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

    workflow_id = str(uuid.uuid4())
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

    workflows = await wait_for_workflows(temporal_client, desc.id, expected_num_workflows, timeout=60)

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
    mock_utcnow, temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""

    # Note the mocked time here, we should stop backfilling at 12 minutes and unpause the job.
    mock_utcnow.return_value = dt.datetime(2023, 1, 1, 0, 12, 12, tzinfo=dt.UTC)

    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = None
    desc = await temporal_schedule_every_5_minutes.describe()

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
    temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule_every_5_minutes.describe()

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
    temporal_worker, temporal_schedule_every_5_minutes, temporal_client, ateam
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted.

    In this test, in contrast to the previous one, we wait until we have started running some
    backfill runs before deleting the schedule.
    """
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule_every_5_minutes.describe()

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
    temporal_worker, failing_s3_batch_export, temporal_client, ateam, clickhouse_client
):
    """Test BackfillBatchExportWorkflow will be cancelled on repeated failures."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)

    # We need some data otherwise the S3 batch export will not fail as it short-circuits.
    for d in date_range(start_at, end_at, dt.timedelta(minutes=5)):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=start_at,
            end_time=end_at,
            count=10,
            inserted_at=d,
            table="sharded_events",
        )

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
    temporal_worker, temporal_schedule_hourly, temporal_client, ateam
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""
    start_at = None
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.UTC)
    desc = await temporal_schedule_hourly.describe()

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
