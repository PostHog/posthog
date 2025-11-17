import uuid
import random
import asyncio
import datetime as dt
import zoneinfo

import pytest
from unittest import mock

from django.conf import settings

import temporalio
import temporalio.client
import temporalio.common
import temporalio.worker
import temporalio.testing
import temporalio.exceptions
from asgiref.sync import sync_to_async
from flaky import flaky

from posthog.models import Team
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
    adjust_bound_datetime_to_schedule_time_zone,
    backfill_range,
    backfill_schedule,
    get_schedule_frequency,
)

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def timezone(request) -> zoneinfo.ZoneInfo:
    try:
        timezone = zoneinfo.ZoneInfo(request.param)
    except AttributeError:
        timezone = zoneinfo.ZoneInfo("UTC")
    return timezone


@pytest.fixture
async def team_with_tz(timezone, aorganization):
    name = f"BatchExportsTestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name, timezone=str(timezone))

    yield team

    await sync_to_async(team.delete)()


@pytest.fixture
async def temporal_schedule_with_tz(temporal_client, team_with_tz):
    """Manage a test Temporal Schedule yielding its handle."""
    batch_export = await acreate_batch_export(
        team_id=team_with_tz.pk,
        name="no-op-export",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval="every 1 minutes",
        paused=True,
    )

    handle = temporal_client.get_schedule_handle(str(batch_export.id))
    yield handle

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
async def temporal_schedule(temporal_client, team):
    """Manage a test Temporal Schedule yielding its handle."""
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name="no-op-export",
        destination_data={
            "type": "NoOp",
            "config": {},
        },
        interval="every 1 minutes",
        paused=True,
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
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.UTC),
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
    ],
)
def test_backfill_range(start_at, end_at, step, expected):
    """Test the backfill_range function yields expected ranges of dates."""
    generator = backfill_range(start_at, end_at, step)
    result = []
    for _ in range(len(expected)):
        result.append(next(generator))

    assert result == expected


@pytest.mark.django_db(transaction=True)
async def test_get_schedule_frequency(activity_environment, temporal_worker, temporal_schedule):
    """Test get_schedule_frequency returns the correct interval."""
    desc = await temporal_schedule.describe()
    expected = desc.schedule.spec.intervals[0].every.total_seconds()

    result = await activity_environment.run(get_schedule_frequency, desc.id)

    assert result == expected


@pytest.mark.django_db(transaction=True)
async def test_backfill_schedule_activity(activity_environment, temporal_worker, temporal_client, temporal_schedule):
    """Test backfill_schedule activity schedules all backfill runs."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.UTC)
    backfill_id = str(uuid.uuid4())

    desc = await temporal_schedule.describe()
    inputs = BackfillScheduleInputs(
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=1.0,
        frequency_seconds=desc.schedule.spec.intervals[0].every.total_seconds(),
        backfill_id=backfill_id,
    )

    await activity_environment.run(backfill_schedule, inputs)

    query = f'TemporalScheduledById="{desc.id}"'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 20
    waited = 0
    expected = 10
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:
                # 1 is EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                args = await workflow.data_converter.decode(
                    event.workflow_execution_started_event_attributes.input.payloads
                )
                assert args[0]["backfill_details"] == {
                    "backfill_id": backfill_id,
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "is_earliest_backfill": False,
                }
            elif event.event_type == 10:
                # 10 is EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                args = await workflow.data_converter.decode(
                    event.activity_task_scheduled_event_attributes.input.payloads
                )
                assert args[0]["backfill_details"] == {
                    "backfill_id": backfill_id,
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "is_earliest_backfill": False,
                }


@pytest.mark.django_db(transaction=True)
async def test_backfill_batch_export_workflow(temporal_worker, temporal_schedule, temporal_client, team):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.UTC)
    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=1.0,
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

    query = f'TemporalScheduledById="{desc.id}"'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 20
    waited = 0
    expected = 10
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    event_backfill_ids = []
    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:
                # 1 is EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                args = await workflow.data_converter.decode(
                    event.workflow_execution_started_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] == start_at.isoformat()
                assert args[0]["backfill_details"]["end_at"] == end_at.isoformat()
                assert args[0]["backfill_details"]["is_earliest_backfill"] is False
            elif event.event_type == 10:
                # 10 is EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                args = await workflow.data_converter.decode(
                    event.activity_task_scheduled_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] == start_at.isoformat()
                assert args[0]["backfill_details"]["end_at"] == end_at.isoformat()
                assert args[0]["backfill_details"]["is_earliest_backfill"] is False

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"
    assert backfill.finished_at is not None

    for backfill_id in event_backfill_ids:
        assert backfill_id == str(backfill.id)


@pytest.mark.django_db(transaction=True)
@mock.patch("products.batch_exports.backend.temporal.backfill_batch_export.get_utcnow")
async def test_backfill_batch_export_workflow_no_end_at(
    mock_utcnow, temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""

    # Note the mocked time here, we should stop backfilling at 8 minutes and unpause the job.
    mock_utcnow.return_value = dt.datetime(2023, 1, 1, 0, 8, 12, tzinfo=dt.UTC)

    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = None
    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
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

    query = f'TemporalScheduledById="{desc.id}"'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 20
    waited = 0
    expected = 8
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    event_backfill_ids = []
    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:
                # 1 is EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                args = await workflow.data_converter.decode(
                    event.workflow_execution_started_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] == start_at.isoformat()
                assert args[0]["backfill_details"]["end_at"] is None
                assert args[0]["backfill_details"]["is_earliest_backfill"] is False
            elif event.event_type == 10:
                # 10 is EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                args = await workflow.data_converter.decode(
                    event.activity_task_scheduled_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] == start_at.isoformat()
                assert args[0]["backfill_details"]["end_at"] is None
                assert args[0]["backfill_details"]["is_earliest_backfill"] is False

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"
    assert backfill.finished_at is not None

    for backfill_id in event_backfill_ids:
        assert backfill_id == str(backfill.id)

    batch_export = await afetch_batch_export(desc.id)
    assert batch_export.paused is False


@pytest.mark.django_db(transaction=True)
@flaky(max_runs=3, min_passes=1)
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted(
    temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
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
    await temporal_schedule.delete()

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.ActivityError)
    assert isinstance(err.__cause__.__cause__, temporalio.exceptions.ApplicationError)
    assert err.__cause__.__cause__.type == "TemporalScheduleNotFoundError"


@pytest.mark.django_db(transaction=True)
@flaky(max_runs=3, min_passes=1)
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted_after_running(
    temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted.

    In this test, in contrats to the previous one, we wait until we have started running some
    backfill runs before cancelling.
    """
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.UTC)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
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

    await temporal_schedule.delete()

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.ActivityError)
    assert isinstance(err.__cause__.__cause__, temporalio.exceptions.ApplicationError)
    assert err.__cause__.__cause__.type == "TemporalScheduleNotFoundError"


@pytest.fixture
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


@pytest.mark.django_db(transaction=True)
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
        start_delay=2.0,
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

    backfills = await afetch_batch_export_backfills(batch_export_id=failing_s3_batch_export.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Cancelled"
    assert backfill.finished_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC", "Europe/Berlin", "Asia/Tokyo", "Pacific/Marquesas", "Asia/Katmandu"],
    indirect=True,
)
async def test_backfill_utc_batch_export_workflow_with_timezone_aware_bounds(
    temporal_worker, temporal_schedule, temporal_client, team, timezone
):
    """Test backfilling a batch export without a timezone set using timezone-aware bounds.

    Temporal schedules can have `time_zone_name` set to `None` in which case Temporal will default to UTC.
    Whenever we try to backfill one of these schedules with a timezone-aware set of bounds, the backfill
    should recognize the disparity and correct it by converting the `datetime` bounds to the timezone
    matching the schedule (UTC in this case).

    There are two things we can do to verify the `datetime` objects are being converted:
    1. Check that the `TemporalScheduledStartTime` search attribute is set to the converted `datetime`. This
    means that re-converting it back to `timezone` should yield a similar `datetime` as the `end_at` we
    passed as input.
    2. Check that the ID of the workflows has been set to a converted `datetime`. Again, reconverting back
    should give us back a similar `datetime` to `end_at`.

    What is "similar" though? Well, we will only match the original `end_at` if we correct for the run's minute
    offset. So, we also adjust that.

    The timezones used in this test include two timezones with fractional hour offsets. The rest were chosen
    arbitrarily.
    """
    hour = 12
    start_at = dt.datetime(2023, 1, 1, hour, 0, 0, tzinfo=timezone)
    end_at = dt.datetime(2023, 1, 1, hour, 10, 0, tzinfo=timezone)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=1.0,
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

    query = f'TemporalScheduledById="{desc.id}" order by StartTime asc'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 60
    waited = 0
    expected = 10
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    adjusted_end_times = []
    adjusted_scheduled_start_times = []
    for index, workflow in enumerate(workflows, start=1):
        run_end_time = dt.datetime.strptime(workflow.id, f"{desc.id}-%Y-%m-%dT%H:%M:%SZ")

        adjusted_minutes = run_end_time.minute + 10 - index
        adjusted_end_times.append(run_end_time.replace(minute=adjusted_minutes).astimezone(timezone))

        temporal_scheduled_start_time = workflow.search_attributes["TemporalScheduledStartTime"][0]

        assert isinstance(temporal_scheduled_start_time, dt.datetime)
        adjusted_scheduled_start_times.append(
            temporal_scheduled_start_time.replace(minute=adjusted_minutes).astimezone(timezone)
        )

    assert all(end_time == end_at for end_time in adjusted_end_times)
    assert all(scheduled_start_time == end_at for scheduled_start_time in adjusted_scheduled_start_times)

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"
    assert backfill.finished_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "timezone",
    ["US/Pacific", "UTC", "Europe/Berlin", "Asia/Tokyo", "Pacific/Marquesas", "Asia/Katmandu"],
    indirect=True,
)
async def test_backfill_aware_batch_export_workflow_with_timezone_aware_bounds(
    temporal_worker, temporal_schedule_with_tz, temporal_client, team_with_tz, timezone
):
    """Test backfilling a batch export with a timezone set using timezone-aware bounds.

    New temporal schedules are timezone aware, and have `time_zone_name` set to a non-`None` value.
    Whenever we try to backfill one of these schedules with a timezone-aware set of bounds that match the
    timezone of the schedule, the backfill should just pass the bounds along without adjusting.

    There are two things we can do to verify the `datetime` objects are being passed correctly:
    1. Check that the `TemporalScheduledStartTime` search attribute is set to the converted original `datetime`
    but converted to UTC timezone (Temporal works only with UTC).
    2. Check that the ID of the workflows has been set to the original `datetime` converted to UTC.

    In both cases, converting the dates back from UTC to their original timezone should yield the original
    `end_at`.

    The timezones used in this test include two timezones with fractional hour offsets. The rest were chosen
    arbitrarily.
    """
    hour = 12
    start_at = dt.datetime(2023, 1, 1, hour, 0, 0, tzinfo=timezone)
    end_at = dt.datetime(2023, 1, 1, hour, 10, 0, tzinfo=timezone)

    desc = await temporal_schedule_with_tz.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team_with_tz.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        start_delay=1.0,
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

    query = f'TemporalScheduledById="{desc.id}" order by StartTime asc'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 60
    waited = 0
    expected = 10
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    adjusted_end_times = []
    adjusted_scheduled_start_times = []
    for index, workflow in enumerate(workflows, start=1):
        run_end_time = dt.datetime.strptime(workflow.id, f"{desc.id}-%Y-%m-%dT%H:%M:%SZ")

        adjusted_minutes = run_end_time.minute + 10 - index
        adjusted_end_times.append(run_end_time.replace(tzinfo=dt.UTC, minute=adjusted_minutes).astimezone(timezone))

        temporal_scheduled_start_time = workflow.search_attributes["TemporalScheduledStartTime"][0]

        assert isinstance(temporal_scheduled_start_time, dt.datetime)
        adjusted_scheduled_start_times.append(
            temporal_scheduled_start_time.replace(minute=adjusted_minutes).astimezone(timezone)
        )

    assert all(end_time == end_at for end_time in adjusted_end_times)
    assert all(scheduled_start_time == end_at for scheduled_start_time in adjusted_scheduled_start_times)

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"
    assert backfill.finished_at is not None


@pytest.mark.django_db(transaction=True)
async def test_backfill_batch_export_workflow_no_start_at(temporal_worker, temporal_schedule, temporal_client, team):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""
    start_at = None
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.UTC)
    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at,
        end_at=end_at.isoformat(),
        start_delay=1.0,
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

    query = f'TemporalScheduledById="{desc.id}"'
    workflows: list[temporalio.client.WorkflowExecution] = []

    timeout = 20
    waited = 0
    expected = 1
    while len(workflows) < expected:
        # It can take a few seconds for workflows to be query-able
        waited += 1
        if waited > timeout:
            raise TimeoutError("Timed-out waiting for workflows to be query-able")

        await asyncio.sleep(1)

        workflows = [workflow async for workflow in temporal_client.list_workflows(query=query)]

    assert len(workflows) == expected

    event_backfill_ids = []
    for workflow in workflows:
        handle = temporal_client.get_workflow_handle(workflow.id)
        history = await handle.fetch_history()

        for event in history.events:
            if event.event_type == 1:
                # 1 is EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
                args = await workflow.data_converter.decode(
                    event.workflow_execution_started_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] is None
                assert args[0]["backfill_details"]["end_at"] == end_at.isoformat()
                assert args[0]["backfill_details"]["is_earliest_backfill"] is True
            elif event.event_type == 10:
                # 10 is EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                args = await workflow.data_converter.decode(
                    event.activity_task_scheduled_event_attributes.input.payloads
                )
                event_backfill_ids.append(args[0]["backfill_details"]["backfill_id"])
                assert args[0]["backfill_details"]["start_at"] is None
                assert args[0]["backfill_details"]["end_at"] == end_at.isoformat()
                assert args[0]["backfill_details"]["is_earliest_backfill"] is True

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"
    assert backfill.finished_at is not None

    for backfill_id in event_backfill_ids:
        assert backfill_id == str(backfill.id)


@pytest.mark.parametrize(
    "bound_dt,schedule_time_zone_name,frequency,expected",
    [
        (
            dt.datetime(2024, 8, 16, 0, 0, 0, tzinfo=zoneinfo.ZoneInfo("US/Pacific")),
            None,
            dt.timedelta(days=1),
            dt.datetime(2024, 8, 16, 0, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        ),
        (
            dt.datetime(2024, 8, 16, 0, 0, 0, tzinfo=zoneinfo.ZoneInfo("US/Pacific")),
            None,
            dt.timedelta(seconds=86400),
            dt.datetime(2024, 8, 16, 0, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        ),
        (
            dt.datetime(2024, 8, 16, 4, 0, 0, tzinfo=zoneinfo.ZoneInfo("US/Pacific")),
            "UTC",
            dt.timedelta(hours=1),
            dt.datetime(2024, 8, 16, 11, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC")),
        ),
        (
            dt.datetime(2024, 8, 16, 4, 0, 0, tzinfo=zoneinfo.ZoneInfo("US/Pacific")),
            "Europe/Berlin",
            dt.timedelta(hours=1),
            dt.datetime(2024, 8, 16, 13, 0, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Berlin")),
        ),
    ],
)
def test_adjust_bound_datetime_to_schedule_time_zone(bound_dt, schedule_time_zone_name, frequency, expected):
    result = adjust_bound_datetime_to_schedule_time_zone(
        bound_dt, schedule_time_zone_name=schedule_time_zone_name, frequency=frequency
    )

    assert result == expected
