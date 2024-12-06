import datetime as dt
import uuid

import pytest
import pytest_asyncio
from freezegun.api import freeze_time
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.temporal.batch_exports.monitoring import (
    BatchExportMonitoringInputs,
    BatchExportMonitoringWorkflow,
    get_batch_export,
    get_event_counts,
)
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
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


@freeze_time(dt.datetime(2023, 4, 25, 15, 30, 0, tzinfo=dt.UTC))
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
async def test_monitoring_workflow(batch_export, generate_test_data, data_interval_start, interval):
    # now = dt.datetime.now(tz=dt.UTC)
    # interval_end = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
    # interval_start = interval_end - dt.timedelta(hours=1)

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
