import asyncio
import datetime as dt
import uuid

import pytest
import pytest_asyncio
import temporalio
import temporalio.client
import temporalio.testing
import temporalio.worker
from django.conf import settings

from posthog.temporal.client import connect
from posthog.temporal.workflows.backfill_batch_export import (
    BackfillBatchExportInputs,
    backfill_range,
    backfill_schedule,
    get_schedule_frequency,
)
from posthog.temporal.workflows.noop import NoOpWorkflow, noop_activity


@pytest_asyncio.fixture
async def temporal_client():
    """Yield a Temporal Client."""
    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )

    return client


@pytest_asyncio.fixture
async def temporal_schedule(temporal_client):
    """Manage a test Temopral Schedule yielding its handle."""
    schedule_id = str(uuid.uuid4())
    handle = await temporal_client.create_schedule(
        schedule_id,
        temporalio.client.Schedule(
            action=temporalio.client.ScheduleActionStartWorkflow(
                NoOpWorkflow.run,
                "test-input",
                id="test-schedule-workflow-id",
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            ),
            spec=temporalio.client.ScheduleSpec(
                intervals=[temporalio.client.ScheduleIntervalSpec(every=dt.timedelta(minutes=1))]
            ),
            state=temporalio.client.ScheduleState(paused=True),
        ),
    )

    yield handle

    await handle.delete()


@pytest.fixture
def temporal_worker(temporal_client):
    worker = temporalio.worker.Worker(
        temporal_client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[NoOpWorkflow],
        activities=[noop_activity],
        workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
    )
    return worker


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


@pytest.mark.asyncio
async def test_get_schedule_frequency(temporal_schedule):
    """Test get_schedule_frequency returns the correct interval."""
    desc = await temporal_schedule.describe()
    expected = desc.schedule.spec.intervals[0].every

    result = await get_schedule_frequency(temporal_schedule)

    assert result == expected


@pytest.mark.asyncio
async def test_backfill_schedule_activity(activity_environment, temporal_worker, temporal_schedule):
    """Test backfill_schedule activity schedules all backfill runs."""
    start_at = dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
    end_at = dt.datetime(2023, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)

    desc = await temporal_schedule.describe()
    inputs = BackfillBatchExportInputs(
        team_id=1,
        schedule_id=desc.id,
        start_at=start_at.isoformat(),
        end_at=end_at.isoformat(),
        buffer_limit=2,
        wait_delay=1.0,
    )
    worker_run = asyncio.create_task(temporal_worker.run())

    await activity_environment.run(backfill_schedule, inputs)

    worker_run.cancel()
    await asyncio.wait([worker_run])

    desc = await temporal_schedule.describe()
    result = desc.info.num_actions
    expected = 10

    assert result == expected
