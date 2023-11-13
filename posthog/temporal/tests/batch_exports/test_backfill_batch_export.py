import datetime as dt
import uuid

import pytest
import pytest_asyncio
import temporalio
import temporalio.client
import temporalio.common
import temporalio.testing
import temporalio.worker
from django.conf import settings

from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_backfills,
)
from posthog.temporal.workflows.backfill_batch_export import (
    BackfillBatchExportInputs,
    BackfillBatchExportWorkflow,
    BackfillScheduleInputs,
    backfill_range,
    backfill_schedule,
    get_schedule_frequency,
)

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture
async def temporal_schedule(temporal_client, team):
    """Manage a test Temopral Schedule yielding its handle."""
    destination_data = {
        "type": "NoOp",
        "config": {},
    }

    interval = "every 1 minutes"
    batch_export_data = {
        "name": "no-op-export",
        "destination": destination_data,
        "interval": interval,
        "paused": True,
    }

    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
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
