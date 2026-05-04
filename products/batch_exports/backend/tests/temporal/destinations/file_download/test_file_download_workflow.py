import uuid
import datetime as dt

import pytest

from django.conf import settings
from django.test import override_settings

import pytest_asyncio
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.models import BatchExportFileDownload
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.service import BatchExportModel, FileDownloadBatchExportInputs
from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.file_download_batch_export import (
    FileDownloadBatchExportWorkflow,
    export_to_file_download_bucket_with_temporary_credentials,
    generate_file_downloads,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    assert_clickhouse_records_in_s3,
    has_valid_credentials,
)
from products.batch_exports.backend.tests.temporal.utils.workflow import fail_on_application_error

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        not has_valid_credentials(),
        reason="AWS credentials not set in environment",
    ),
]


@pytest_asyncio.fixture
async def file_download_batch_export(
    ateam,
    interval,
    exclude_events,
    temporal_client,
    compression,
    file_format,
):
    destination_data = {
        "type": "FileDownload",
        "config": {
            "file_format": file_format,
            "compression": compression,
        },
    }

    batch_export_data = {
        "name": "my-file-download-destination",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
async def test_file_download_workflow_exports_data(
    clickhouse_client,
    s3_client,
    ateam,
    file_download_batch_export,
    s3_bucket,
    interval,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel,
    generate_test_data,
    aws_role_arn,
    region,
):
    """Test FileDownloadBatchExportWorkflow end-to-end.

    The workflow should:
    1. Start a batch export run.
    2. Insert data into the internal stage.
    3. Export data from the internal stage to the file download S3 bucket using temporary credentials.
    4. Generate file download records for the exported files.
    5. Complete with the correct records_completed count.
    """
    batch_export_id = str(file_download_batch_export.id)

    workflow_id = str(uuid.uuid4())
    inputs = FileDownloadBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        data_interval_end=data_interval_end.isoformat(),
        data_interval_start=data_interval_start.isoformat(),
        interval=interval,
        batch_export_model=model,
        file_format=file_format,
        compression=compression,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[FileDownloadBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                finish_batch_export_run,
                insert_into_internal_stage_activity,
                export_to_file_download_bucket_with_temporary_credentials,
                generate_file_downloads,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                fail_on_application_error(),
                override_settings(
                    BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET=s3_bucket,
                    BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN=aws_role_arn,
                    BATCH_EXPORTS_FILE_DOWNLOAD_REGION=region,
                ),
            ):
                await activity_environment.client.execute_workflow(
                    FileDownloadBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=30),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export_id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed is not None
    assert run.records_completed > 0

    events_to_export_created, _ = generate_test_data
    assert run.records_completed == len(events_to_export_created)

    prefix = (
        f"batch-exports/{batch_export_id}/{run.id}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}"
    )
    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=s3_bucket,
        key_prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        compression=compression,
        file_format=file_format,
        sort_key="uuid",
    )

    # Verify BatchExportFileDownload records were created by the workflow.
    file_downloads = [
        file_download
        async for file_download in BatchExportFileDownload.objects.filter(team_id=ateam.pk, batch_export_run_id=run.id)
    ]
    assert len(file_downloads) > 0

    # Each file download should reference a valid S3 key under the expected prefix.
    for fd in file_downloads:
        assert fd.team_id == ateam.pk
        assert fd.batch_export_run_id == run.id
        assert fd.key.startswith(f"batch-exports/{batch_export_id}/")
        assert fd.created_at is not None

    # The S3 keys referenced by file downloads should correspond to actual objects in the bucket.
    for fd in file_downloads:
        response = await s3_client.head_object(Bucket=s3_bucket, Key=fd.key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
