import datetime as dt
import uuid

import pytest
import pytest_asyncio
from freezegun.api import freeze_time
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.models import BatchExportRun
from posthog.temporal.batch_exports.monitoring import (
    BatchExportMonitoringInputs,
    BatchExportMonitoringWorkflow,
    get_batch_export,
    get_event_counts,
    update_batch_export_runs,
)
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest_asyncio.fixture
async def batch_export(ateam, temporal_client):
    """Provide a batch export for tests, not intended to be used."""
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "a-bucket",
            "region": "us-east-1",
            "prefix": "a-key",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "every 5 minutes",
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],  # type: ignore
        destination_data=batch_export_data["destination"],  # type: ignore
        interval=batch_export_data["interval"],  # type: ignore
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest_asyncio.fixture
async def generate_batch_export_runs(
    generate_test_data,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    interval: str,
    batch_export,
):
    # to keep things simple for now, we assume 5 min interval
    if interval != "every 5 minutes":
        raise NotImplementedError("Only 5 minute intervals are supported for now. Please update the test.")

    events_created, _ = generate_test_data

    batch_export_runs: list[BatchExportRun] = []
    interval_start = data_interval_start
    interval_end = interval_start + dt.timedelta(minutes=5)
    while interval_end <= data_interval_end:
        run = BatchExportRun(
            batch_export_id=batch_export.id,
            data_interval_start=interval_start,
            data_interval_end=interval_end,
            status="completed",
            records_completed=len(
                [
                    e
                    for e in events_created
                    if interval_start
                    <= dt.datetime.fromisoformat(e["inserted_at"]).replace(tzinfo=dt.UTC)
                    < interval_end
                ]
            ),
        )
        await run.asave()
        batch_export_runs.append(run)
        interval_start = interval_end
        interval_end += dt.timedelta(minutes=5)

    yield

    for run in batch_export_runs:
        await run.adelete()


async def test_monitoring_workflow_when_no_event_data(batch_export):
    workflow_id = str(uuid.uuid4())
    inputs = BatchExportMonitoringInputs(team_id=batch_export.team_id)
    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            # TODO - not sure if this is the right task queue
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[BatchExportMonitoringWorkflow],
            activities=[
                get_batch_export,
                get_event_counts,
                update_batch_export_runs,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            batch_export_runs_updated = await activity_environment.client.execute_workflow(
                BatchExportMonitoringWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )
            assert batch_export_runs_updated == 0


@freeze_time()
@pytest.mark.parametrize(
    "data_interval_start",
    # This is hardcoded relative to the `data_interval_end` used in all or most tests, since that's also
    # passed to `generate_test_data` to determine the timestamp for the generated data.
    # This will generate 2 hours of data between 13:00 and 15:00.
    [dt.datetime(2023, 4, 25, 13, 0, 0, tzinfo=dt.UTC)],
    indirect=True,
)
@pytest.mark.parametrize(
    "interval",
    ["every 5 minutes"],
    indirect=True,
)
async def test_monitoring_workflow(
    batch_export, generate_test_data, data_interval_start, interval, generate_batch_export_runs
):
    """Test the monitoring workflow with a batch export that has data.

    We generate 2 hours of data between 13:00 and 15:00, and then run the
    monitoring workflow at 15:30.  The monitoring workflow should check the data
    between 14:00 and 15:00, and update the batch export runs.

    We generate some dummy batch export runs based on the event data we
    generated and assert that the expected records count matches the records
    completed.
    """
    workflow_id = str(uuid.uuid4())
    inputs = BatchExportMonitoringInputs(team_id=batch_export.team_id)

    with freeze_time(dt.datetime(2023, 4, 25, 15, 30, 0, tzinfo=dt.UTC)) as frozen_time:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                # TODO - not sure if this is the right task queue
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                workflows=[BatchExportMonitoringWorkflow],
                activities=[
                    get_batch_export,
                    get_event_counts,
                    update_batch_export_runs,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(
                    BatchExportMonitoringWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=30),
                )

        # the monitoring workflow checks a single hour of data
        check_interval_end = frozen_time().replace(minute=0, second=0, microsecond=0, tzinfo=dt.UTC) - dt.timedelta(
            hours=1
        )
        check_interval_start = check_interval_end - dt.timedelta(hours=1)
        batch_export_runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        for run in batch_export_runs:
            if run.data_interval_start is None:
                continue
            if run.data_interval_start >= check_interval_end or run.data_interval_end < check_interval_start:
                # we shouldn't have updated this run
                assert run.expected_records_count is None
            elif run.records_completed == 0:
                # TODO: in the actual monitoring activity it would be better to
                # update the actual count to 0 rather than None
                assert run.expected_records_count is None
            else:
                assert run.records_completed == run.expected_records_count
