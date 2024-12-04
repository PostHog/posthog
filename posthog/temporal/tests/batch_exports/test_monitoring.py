import datetime as dt
import uuid

import pytest
import pytest_asyncio
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.temporal.batch_exports.monitoring import (
    BatchExportMonitoringInputs,
    BatchExportMonitoringWorkflow,
    compare_counts,
    get_batch_export,
    get_events_count,
    get_records_completed,
)
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_TIME = dt.datetime.now(dt.UTC)


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
        "interval": "hour",
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],  # type: ignore
        destination_data=batch_export_data["destination"],  # type: ignore
        interval=batch_export_data["interval"],  # type: ignore
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


async def test_monitoring_workflow(batch_export):
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
                get_records_completed,
                get_events_count,
                compare_counts,
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
