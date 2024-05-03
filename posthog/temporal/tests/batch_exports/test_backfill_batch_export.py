import datetime as dt
import uuid
from unittest import mock

import pytest
import pytest_asyncio
import temporalio
import temporalio.client
import temporalio.common
import temporalio.exceptions
import temporalio.testing
import temporalio.worker
from asgiref.sync import sync_to_async
from django.conf import settings

from posthog.temporal.batch_exports.backfill_batch_export import (
    BackfillBatchExportInputs,
    BackfillBatchExportWorkflow,
    BackfillScheduleInputs,
    backfill_range,
    backfill_schedule,
    get_schedule_frequency,
    wait_for_schedule_backfill_in_range,
)
from posthog.temporal.tests.utils.datetimes import date_range
from posthog.temporal.tests.utils.events import (
    generate_test_events_in_clickhouse,
)
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export,
    afetch_batch_export_backfills,
)

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture
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
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
                )
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2023, 1, 1, 12, 20, 0, tzinfo=dt.timezone.utc),
            dt.timedelta(hours=1),
            [
                (
                    dt.datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.timezone.utc),
                ),
                (
                    dt.datetime(2023, 1, 1, 11, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.timedelta(hours=12),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc),
                ),
                (
                    dt.datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
                ),
            ],
        ),
        (
            dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc),
            dt.timedelta(days=1),
            [
                (
                    dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
                ),
                (
                    dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.timezone.utc),
                ),
                (
                    dt.datetime(2023, 1, 3, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.timezone.utc),
                ),
                (
                    dt.datetime(2023, 1, 4, 0, 0, 0, tzinfo=dt.timezone.utc),
                    dt.datetime(2023, 1, 5, 0, 0, 0, tzinfo=dt.timezone.utc),
                ),
            ],
        ),
    ],
)
def test_backfill_range(start_at, end_at, step, expected):
    """Test the backfill_range function yields expected ranges of dates."""
    result = list(backfill_range(start_at, end_at, step))
    assert result == expected


@pytest.mark.django_db(transaction=True)
async def test_get_schedule_frequency(activity_environment, temporal_worker, temporal_schedule):
    """Test get_schedule_frequency returns the correct interval."""
    desc = await temporal_schedule.describe()
    expected = desc.schedule.spec.intervals[0].every.total_seconds()

    result = await activity_environment.run(get_schedule_frequency, desc.id)

    assert result == expected


@pytest.mark.django_db(transaction=True)
async def test_backfill_schedule_activity(activity_environment, temporal_worker, temporal_schedule):
    """Test backfill_schedule activity schedules all backfill runs."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)

    desc = await temporal_schedule.describe()
    inputs = BackfillScheduleInputs(
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=2,
        wait_delay=1.0,
        frequency_seconds=desc.schedule.spec.intervals[0].every.total_seconds(),
    )

    await activity_environment.run(backfill_schedule, inputs)

    desc = await temporal_schedule.describe()
    result = desc.info.num_actions
    expected = 10

    assert result >= expected


@pytest.mark.django_db(transaction=True)
async def test_backfill_batch_export_workflow(temporal_worker, temporal_schedule, temporal_client, team):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=2,
        wait_delay=1.0,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    desc = await temporal_schedule.describe()
    result = desc.info.num_actions
    expected = 10

    assert result == expected

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"


@pytest.mark.django_db(transaction=True)
@mock.patch("posthog.temporal.batch_exports.backfill_batch_export.get_utcnow")
async def test_backfill_batch_export_workflow_no_end_at(
    mock_utcnow, temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow executes all backfill runs and updates model."""

    # Note the mocked time here, we should stop backfilling at 8 minutes and unpause the job.
    mock_utcnow.return_value = dt.datetime(2023, 1, 1, 0, 8, 12, tzinfo=dt.timezone.utc)

    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = None

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at,
        buffer_limit=2,
        wait_delay=0.1,
    )

    batch_export = await afetch_batch_export(desc.id)
    assert batch_export.paused is True

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await handle.result()

    desc = await temporal_schedule.describe()
    result = desc.info.num_actions
    expected = 8

    assert result == expected

    backfills = await afetch_batch_export_backfills(batch_export_id=desc.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Completed"

    batch_export = await afetch_batch_export(desc.id)
    assert batch_export.paused is False


@pytest.mark.django_db(transaction=True)
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted(
    temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=1,
        wait_delay=2.0,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
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
async def test_backfill_batch_export_workflow_fails_when_schedule_deleted_after_running(
    temporal_worker, temporal_schedule, temporal_client, team
):
    """Test BackfillBatchExportWorkflow fails when its underlying Temporal Schedule is deleted.

    In this test, in contrats to the previous one, we wait until we have started running some
    backfill runs before cancelling.
    """
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)

    desc = await temporal_schedule.describe()

    workflow_id = str(uuid.uuid4())
    inputs = BackfillBatchExportInputs(
        team_id=team.pk,
        batch_export_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=1,
        wait_delay=2.0,
    )

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        execution_timeout=dt.timedelta(seconds=20),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )
    await wait_for_schedule_backfill_in_range(
        client=temporal_client,
        schedule_id=desc.id,
        start_at=start_at,
        end_at=dt.datetime(2023, 1, 1, 0, 1, 0, tzinfo=dt.timezone.utc),
        now=now,
        wait_delay=1.0,
    )

    desc = await temporal_schedule.describe()
    result = desc.info.num_actions

    assert result >= 1

    await temporal_schedule.delete()

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
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)

    # We need some data otherwise the S3 batch export will not fail as it short-circuits.
    for d in date_range(start_at, end_at, dt.timedelta(minutes=5)):
        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=start_at,
            end_time=end_at,
            count=10,
            inserted_at=d,
        )

    inputs = BackfillBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(failing_s3_batch_export.id),
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=2,
        wait_delay=1.0,
    )

    # Need to recreate the specific ID the app would use when triggering a backfill
    start_at_str = start_at.strftime("%Y-%m-%dT%H:%M:%S")
    end_at_str = end_at.strftime("%Y-%m-%dT%H:%M:%S")
    backfill_id = f"{failing_s3_batch_export.id}-Backfill-{start_at_str}-{end_at_str}"

    handle = await temporal_client.start_workflow(
        BackfillBatchExportWorkflow.run,
        inputs,
        id=backfill_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        execution_timeout=dt.timedelta(minutes=2),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
    )

    with pytest.raises(temporalio.client.WorkflowFailureError) as exc_info:
        await handle.result()

    err = exc_info.value
    assert isinstance(err.__cause__, temporalio.exceptions.CancelledError)

    await sync_to_async(failing_s3_batch_export.refresh_from_db)()
    assert failing_s3_batch_export.paused is True

    backfills = await afetch_batch_export_backfills(batch_export_id=failing_s3_batch_export.id)

    assert len(backfills) == 1, "Expected one backfill to have been created"

    backfill = backfills.pop()
    assert backfill.status == "Cancelled"
