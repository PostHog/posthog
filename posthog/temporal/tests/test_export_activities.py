import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import temporalio.workflow
from asgiref.sync import sync_to_async
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.activities import export_asset_activity, record_export_failure_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult, RecordExportFailureInputs

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import ExcelColumnLimitExceeded, ExportCancelled

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@temporalio.workflow.defn(name="test-export-asset")
class TestExportAssetWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]):
        return {}

    @temporalio.workflow.run
    async def run(self, inputs: ExportAssetActivityInputs) -> ExportAssetResult:
        return await temporalio.workflow.execute_activity(
            export_asset_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=EXPORT_RETRY_POLICY,
        )


@asynccontextmanager
async def export_worker(client: Client):
    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[TestExportAssetWorkflow],
        activities=[export_asset_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
        activity_executor=ThreadPoolExecutor(max_workers=5),
        debug_mode=True,
    ):
        yield


async def run_export_workflow(client: Client, asset_id: int) -> ExportAssetResult:
    return await client.execute_workflow(
        TestExportAssetWorkflow.run,
        ExportAssetActivityInputs(exported_asset_id=asset_id),
        id=str(uuid.uuid4()),
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )


@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_activity_success(mock_exporter: MagicMock, team):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format=ExportedAsset.ExportFormat.PNG,
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/key"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with export_worker(env.client):
            result = await run_export_workflow(env.client, asset.id)

    assert result.exported_asset_id == asset.id
    assert result.success is True
    assert result.error is None


@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_activity_propagates_user_errors(mock_exporter: MagicMock, team):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format=ExportedAsset.ExportFormat.PNG,
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.failure_type = "user"
        asset_obj.exception_type = "ExcelColumnLimitExceeded"
        asset_obj.save(update_fields=["failure_type", "exception_type"])
        raise ExcelColumnLimitExceeded()

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with export_worker(env.client):
            with pytest.raises(WorkflowFailureError) as exc_info:
                await run_export_workflow(env.client, asset.id)

    wf_error = exc_info.value
    assert isinstance(wf_error, WorkflowFailureError)
    activity_error = wf_error.cause
    assert isinstance(activity_error, ActivityError)
    app_error = activity_error.cause
    assert app_error is not None
    assert "ExcelColumnLimitExceeded" in str(app_error) or "18,278 columns" in str(app_error)


@pytest.mark.parametrize(
    "exception,expected_non_retryable",
    [
        (TimeoutError("Timeout while waiting for the page to load"), False),
        (PlaywrightTimeoutError("Timeout 30000ms exceeded"), False),
        (ExportCancelled("export canceled"), True),
        (ValueError("bad input"), True),
    ],
)
@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_activity_timeout_errors_are_retryable(
    mock_exporter: MagicMock, activity_environment, team, exception, expected_non_retryable
):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format=ExportedAsset.ExportFormat.PNG,
    )

    def fake_export(asset_obj, **kwargs):
        raise exception

    mock_exporter.export_asset_direct = fake_export

    with pytest.raises(ApplicationError) as exc_info:
        await activity_environment.run(export_asset_activity, ExportAssetActivityInputs(exported_asset_id=asset.id))

    assert exc_info.value.non_retryable is expected_non_retryable


async def test_record_export_failure_activity_records_on_empty_asset(activity_environment, team):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format=ExportedAsset.ExportFormat.CSV,
    )

    await activity_environment.run(
        record_export_failure_activity,
        RecordExportFailureInputs(
            exported_asset_id=asset.id,
            message="Export failed to complete",
            exception_type="TimeoutError",
        ),
    )

    await sync_to_async(asset.refresh_from_db)()
    assert asset.exception == "Export failed to complete"
    assert asset.exception_type == "TimeoutError"
    # TimeoutError classifies as a generation timeout via failure_handler
    assert asset.failure_type == "timeout_generation"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exception": "the real error", "exception_type": "QueryError"},
        {"content": b"already-has-bytes"},
    ],
    ids=["existing_exception", "has_content"],
)
async def test_record_export_failure_activity_does_not_clobber_terminal_state(activity_environment, team, kwargs):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format=ExportedAsset.ExportFormat.CSV,
        **kwargs,
    )

    await activity_environment.run(
        record_export_failure_activity,
        RecordExportFailureInputs(
            exported_asset_id=asset.id,
            message="should not overwrite",
            exception_type="TimeoutError",
        ),
    )

    await sync_to_async(asset.refresh_from_db)()
    assert asset.exception == kwargs.get("exception")
