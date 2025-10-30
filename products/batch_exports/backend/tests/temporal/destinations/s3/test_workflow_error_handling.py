import uuid
import typing as t
import asyncio
import datetime as dt
import contextlib

import pytest
from unittest import mock

import aioboto3
import botocore.exceptions
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from types_aiobotocore_s3.client import S3Client

from posthog import constants
from posthog.batch_exports.service import BatchExportModel
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    ConcurrentS3Consumer,
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    insert_into_s3_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import assert_clickhouse_records_in_s3
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class RetryableTestException(Exception):
    pass


async def test_s3_export_workflow_handles_unexpected_insert_activity_errors(ateam, s3_batch_export, interval):
    """Test S3BatchExport Workflow can handle unexpected errors from executing the insert into S3 activity.

    This means we do the right updates to the BatchExportRun model and ensure the workflow fails (since we
    treat this as an unexpected internal error).

    To simulate an unexpected error, we mock the `ProducerFromInternalStage.start` activity. It doesn't matter where
    the exception is raised, but since the insert into stage activity doesn't actually generate any data, we need to
    raise it before the activity completes early.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                insert_into_s3_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "products.batch_exports.backend.temporal.destinations.s3_batch_export.ProducerFromInternalStage.start",
                side_effect=RetryableTestException("A useful error message"),
            ):
                with pytest.raises(WorkflowFailureError):
                    await activity_environment.client.execute_workflow(
                        S3BatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "RetryableTestException: A useful error message"
    assert run.records_completed is None
    assert run.bytes_exported is None


async def test_s3_export_workflow_handles_insert_activity_non_retryable_errors(ateam, s3_batch_export, interval):
    """Test S3BatchExport Workflow can handle non-retryable errors from executing the insert into S3 activity.

    This means we do the right updates to the BatchExportRun model and ensure the workflow succeeds (since we
    treat this as a user error).

    To simulate a user error, we mock the `ProducerFromInternalStage.start` activity. It doesn't matter where
    the exception is raised, but since the insert into stage activity doesn't actually generate any data, we need to
    raise it before the activity completes early.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    class ParamValidationError(Exception):
        pass

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                insert_into_s3_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "products.batch_exports.backend.temporal.destinations.s3_batch_export.ProducerFromInternalStage.start",
                side_effect=ParamValidationError("A useful error message"),
            ):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ParamValidationError: A useful error message"


async def test_s3_export_workflow_handles_cancellation(ateam, s3_batch_export, interval):
    """Test that S3 Export Workflow can gracefully handle cancellations when inserting S3 data.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    @activity.defn(name="insert_into_s3_activity_from_stage")
    async def never_finish_activity_from_stage(_):
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                never_finish_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

        runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Cancelled"
        assert run.latest_error == "Cancelled"


async def test_s3_export_workflow_with_request_timeouts(
    clickhouse_client,
    ateam,
    minio_client,
    bucket_name,
    interval,
    s3_batch_export,
    s3_key_prefix,
    data_interval_end,
    data_interval_start,
    generate_test_data,
):
    """Test the S3BatchExport Workflow end-to-end when a `RequestTimeout` occurs.

    We run the S3 batch export workflow with a mocked session that will raise a `ClientError` due
    to a `RequestTimeout` on the first run of the batch export. The second run should work normally.
    """
    batch_export_model = BatchExportModel(name="events", schema=None)
    batch_export_schema = None

    raised = 0

    class FakeSession(aioboto3.Session):
        @contextlib.asynccontextmanager
        async def client(self, *args, **kwargs):  # type: ignore
            async with self._session.create_client(*args, **kwargs) as client:
                client = t.cast(S3Client, client)
                original_upload_part = client.upload_part

                async def faulty_upload_part(*args, **kwargs):
                    nonlocal raised

                    if raised < 5:
                        raised = raised + 1
                        raise botocore.exceptions.ClientError(
                            error_response={
                                "Error": {"Code": "RequestTimeout", "Message": "Oh no!"},
                                "ResponseMetadata": {"MaxAttemptsReached": True, "RetryAttempts": 2},  # type: ignore
                            },
                            operation_name="UploadPart",
                        )
                    else:
                        return await original_upload_part(*args, **kwargs)

                client.upload_part = faulty_upload_part  # type: ignore

                yield client

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                finish_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_s3_activity_from_stage,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        with (
            mock.patch(
                "products.batch_exports.backend.temporal.destinations.s3_batch_export.aioboto3.Session",
                FakeSession,
            ),
            mock.patch.object(ConcurrentS3Consumer, "MAX_RETRY_DELAY", 0.01),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=2),
                execution_timeout=dt.timedelta(minutes=2),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 2
    runs.sort(key=lambda r: r.last_updated_at)

    run = runs[0]
    (events_to_export_created, persons_to_export_created) = generate_test_data
    assert run.status == "FailedRetryable"
    assert run.records_completed is None
    assert run.bytes_exported is None
    assert (
        run.latest_error
        == "IntermittentUploadPartTimeoutError: An intermittent `RequestTimeout` was raised while attempting to upload part 1"
    )

    run = runs[1]
    (events_to_export_created, persons_to_export_created) = generate_test_data
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created) or run.records_completed == len(
        persons_to_export_created
    )
    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    assert runs[0].data_interval_end == runs[1].data_interval_end

    expected_key_prefix = s3_key_prefix.format(
        table=batch_export_model.name if batch_export_model is not None else "events",
        year=data_interval_end.year,
        month=data_interval_end.strftime("%m"),
        day=data_interval_end.strftime("%d"),
        hour=data_interval_end.strftime("%H"),
        minute=data_interval_end.strftime("%M"),
        second=data_interval_end.strftime("%S"),
    )

    objects = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=expected_key_prefix)
    key = objects["Contents"][0].get("Key")
    assert len(objects.get("Contents", [])) == 1
    assert key.startswith(expected_key_prefix)

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=expected_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=batch_export_model,
        sort_key=sort_key,
    )
