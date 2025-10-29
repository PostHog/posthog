import uuid
import functools
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

import pandas as pd
import aioboto3
import pytest_asyncio
from asgiref.sync import sync_to_async
from deltalake import write_deltalake
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.constants import DATA_WAREHOUSE_COMPACTION_TASK_QUEUE
from posthog.models.team.team import Team
from posthog.temporal.data_imports.deltalake_compaction_job import DeltalakeCompactionJobWorkflowInputs
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.settings import ACTIVITIES, DeltalakeCompactionJobWorkflow

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource

BUCKET_NAME = "test-pipeline"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest_asyncio.fixture(autouse=True)
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        try:
            await minio_client.head_bucket(Bucket=BUCKET_NAME)
        except:
            await minio_client.create_bucket(Bucket=BUCKET_NAME)

        yield minio_client


async def _run(team: Team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Postgres",
        job_inputs={},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="SomeTable",
        team_id=team.pk,
        source_id=source.pk,
        sync_type="full_refresh",
        sync_type_config={},
    )

    job = await sync_to_async(ExternalDataJob.objects.create)(
        team_id=team.pk,
        pipeline_id=source.pk,
        schema_id=schema.pk,
        rows_synced=0,
        status=ExternalDataJob.Status.COMPLETED,
    )
    with override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        AIRBYTE_BUCKET_REGION="us-east-1",
        AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job_folder_path = await sync_to_async(job.folder_path)()
        deltalake_url = f"{settings.BUCKET_URL}/{job_folder_path}/{schema.normalized_name}"

        df = pd.DataFrame({"id": [1], "col": ["hello"]})
        write_deltalake(
            deltalake_url,
            df,
            storage_options={
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            },
        )

        inputs = DeltalakeCompactionJobWorkflowInputs(team_id=team.pk, external_data_job_id=job.id)

        with mock.patch.object(DeltaTableHelper, "compact_table") as mock_compact_table:
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=DATA_WAREHOUSE_COMPACTION_TASK_QUEUE,
                    workflows=[DeltalakeCompactionJobWorkflow],
                    activities=ACTIVITIES,  # type: ignore
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=50),
                    max_concurrent_activities=50,
                ):
                    await activity_environment.client.execute_workflow(
                        DeltalakeCompactionJobWorkflow.run,
                        inputs,
                        id=str(uuid.uuid4()),
                        task_queue=DATA_WAREHOUSE_COMPACTION_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

        mock_compact_table.assert_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_compaction_job(team):
    await _run(team)
