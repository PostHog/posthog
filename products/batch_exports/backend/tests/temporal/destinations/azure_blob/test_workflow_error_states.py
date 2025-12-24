import asyncio
import datetime as dt

import pytest
from unittest import mock

from django.conf import settings

from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run
from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    AzureBlobBatchExportInputs,
    AzureBlobBatchExportWorkflow,
    insert_into_azure_blob_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import BatchExportInsertIntoInternalStageInputs
from products.batch_exports.backend.tests.temporal.utils.workflow import mocked_start_batch_export_run

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class RetryableTestException(Exception):
    pass


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_sets_failed_retryable_on_transient_error(
    ateam,
    azure_batch_export,
):
    """Test that transient errors result in FailedRetryable status."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = f"azure-error-test-{azure_batch_export.id}"
    inputs = AzureBlobBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(azure_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval="hour",
        container_name=azure_batch_export.destination.config["container_name"],
        prefix=azure_batch_export.destination.config["prefix"],
        file_format="JSONLines",
        compression=None,
        integration_id=azure_batch_export.destination.integration.id,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[AzureBlobBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                insert_into_azure_blob_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "products.batch_exports.backend.temporal.destinations.azure_blob_batch_export.ProducerFromInternalStage.start",
                side_effect=RetryableTestException("Transient network error"),
            ):
                with pytest.raises(WorkflowFailureError):
                    await activity_environment.client.execute_workflow(
                        AzureBlobBatchExportWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

    runs = await afetch_batch_export_runs(batch_export_id=azure_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert "RetryableTestException: Transient network error" in run.latest_error


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_sets_failed_on_container_not_found(
    ateam,
    azure_batch_export,
):
    """Test that ContainerNotFound results in Failed status (non-retryable user error)."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = f"azure-error-test-{azure_batch_export.id}"
    inputs = AzureBlobBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(azure_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval="hour",
        container_name=azure_batch_export.destination.config["container_name"],
        prefix=azure_batch_export.destination.config["prefix"],
        file_format="JSONLines",
        compression=None,
        integration_id=azure_batch_export.destination.integration.id,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[AzureBlobBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                insert_into_azure_blob_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "products.batch_exports.backend.temporal.destinations.azure_blob_batch_export.ProducerFromInternalStage.start",
                side_effect=ResourceNotFoundError("Container not found"),
            ):
                await activity_environment.client.execute_workflow(
                    AzureBlobBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=azure_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert "ResourceNotFoundError" in run.latest_error


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_sets_failed_on_invalid_credentials(
    ateam,
    azure_batch_export,
):
    """Test that invalid credentials result in Failed status (non-retryable user error)."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = f"azure-error-test-{azure_batch_export.id}"
    inputs = AzureBlobBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(azure_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval="hour",
        container_name=azure_batch_export.destination.config["container_name"],
        prefix=azure_batch_export.destination.config["prefix"],
        file_format="JSONLines",
        compression=None,
        integration_id=azure_batch_export.destination.integration.id,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[AzureBlobBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                insert_into_azure_blob_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "products.batch_exports.backend.temporal.destinations.azure_blob_batch_export.ProducerFromInternalStage.start",
                side_effect=ClientAuthenticationError("Invalid credentials"),
            ):
                await activity_environment.client.execute_workflow(
                    AzureBlobBatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=azure_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert "ClientAuthenticationError" in run.latest_error


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("file_format", ["JSONLines"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
async def test_workflow_sets_cancelled_on_cancellation(
    ateam,
    azure_batch_export,
):
    """Test that cancelled workflow results in Cancelled status."""
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = f"azure-error-test-{azure_batch_export.id}"
    inputs = AzureBlobBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(azure_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval="hour",
        container_name=azure_batch_export.destination.config["container_name"],
        prefix=azure_batch_export.destination.config["prefix"],
        file_format="JSONLines",
        compression=None,
        integration_id=azure_batch_export.destination.integration.id,
    )

    @activity.defn(name="insert_into_internal_stage_activity")
    async def insert_into_internal_stage_activity_mocked(_: BatchExportInsertIntoInternalStageInputs):
        return

    @activity.defn(name="insert_into_azure_blob_activity_from_stage")
    async def never_finish_activity(_):
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[AzureBlobBatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_internal_stage_activity_mocked,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                AzureBlobBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

        runs = await afetch_batch_export_runs(batch_export_id=azure_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Cancelled"
        assert run.latest_error == "Cancelled"
