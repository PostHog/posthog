from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.exported_asset import ExportedAsset
from posthog.slo.types import SloOutcome
from posthog.temporal.exports.activities import emit_export_outcome, export_asset_activity
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@patch("posthog.slo.events.posthoganalytics")
@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_workflow_success_emits_slo_completed(
    mock_exporter: MagicMock,
    mock_analytics: MagicMock,
    team,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format="image/png",
    )

    def fake_export(asset_obj, **kwargs):
        asset_obj.content_location = "s3://bucket/test.png"
        asset_obj.save(update_fields=["content_location"])

    mock_exporter.export_asset_direct = fake_export

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[ExportAssetWorkflow],
            activities=[export_asset_activity, emit_export_outcome],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=5),
            debug_mode=True,
        ):
            await env.client.execute_workflow(
                ExportAssetWorkflow.run,
                ExportAssetWorkflowInputs(
                    exported_asset_id=asset.id,
                    team_id=team.id,
                    source="web",
                    export_format="image/png",
                ),
                id=f"export-asset-{asset.id}",
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

    await sync_to_async(asset.refresh_from_db)()
    assert asset.has_content

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    props = completed_calls[0].kwargs["properties"]
    assert props["outcome"] == SloOutcome.SUCCESS
    assert props["operation"] == "export"
    assert props["exported_asset_id"] == asset.id
    assert props["export_format"] == "image/png"
    assert props["source"] == "web"


@patch("posthog.slo.events.posthoganalytics")
@patch("posthog.temporal.exports.activities.exporter")
async def test_export_asset_workflow_failure_emits_slo_failure(
    mock_exporter: MagicMock,
    mock_analytics: MagicMock,
    team,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team,
        export_format="image/png",
    )

    mock_exporter.export_asset_direct = MagicMock(side_effect=RuntimeError("Chrome crashed"))

    with pytest.raises(Exception):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[ExportAssetWorkflow],
                activities=[export_asset_activity, emit_export_outcome],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=5),
                debug_mode=True,
            ):
                await env.client.execute_workflow(
                    ExportAssetWorkflow.run,
                    ExportAssetWorkflowInputs(
                        exported_asset_id=asset.id,
                        team_id=team.id,
                        source="web",
                        export_format="image/png",
                    ),
                    id=f"export-asset-{asset.id}",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    props = completed_calls[0].kwargs["properties"]
    assert props["outcome"] == SloOutcome.FAILURE
    assert props["error"] is not None
