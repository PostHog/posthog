import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

import temporalio.workflow
from asgiref.sync import sync_to_async
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.exported_asset import ExportedAsset
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult


@temporalio.workflow.defn(name="test-export-asset")
class TestExportAssetWorkflow(PostHogWorkflow):
    """Minimal wrapper workflow so we can test the activity via Temporal."""

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


pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_activity_success(
    mock_exporter: MagicMock,
    team,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format="image/png",
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/key"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[TestExportAssetWorkflow],
            activities=[export_asset_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=5),
            debug_mode=True,
        ):
            result = await env.client.execute_workflow(
                TestExportAssetWorkflow.run,
                ExportAssetActivityInputs(exported_asset_id=asset.id),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    assert result.exported_asset_id == asset.id
    assert result.success is True
    assert result.exception_class is None


@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_activity_propagates_user_errors(
    mock_exporter: MagicMock,
    team,
):
    from posthog.tasks.exports.failure_handler import ExcelColumnLimitExceeded

    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format="image/png",
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.failure_type = "user"
        asset_obj.exception_type = "ExcelColumnLimitExceeded"
        asset_obj.save(update_fields=["failure_type", "exception_type"])
        raise ExcelColumnLimitExceeded()

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[TestExportAssetWorkflow],
            activities=[export_asset_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=5),
            debug_mode=True,
        ):
            with pytest.raises(WorkflowFailureError) as exc_info:
                await env.client.execute_workflow(
                    TestExportAssetWorkflow.run,
                    ExportAssetActivityInputs(exported_asset_id=asset.id),
                    id=str(uuid.uuid4()),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )

        # WorkflowFailureError.cause is ActivityError; ActivityError.cause is the ApplicationError
        wf_error = exc_info.value
        assert isinstance(wf_error, WorkflowFailureError)
        activity_error = wf_error.cause
        assert isinstance(activity_error, ActivityError)
        app_error = activity_error.cause
        assert app_error is not None
        assert "ExcelColumnLimitExceeded" in str(app_error) or "18,278 columns" in str(app_error)
