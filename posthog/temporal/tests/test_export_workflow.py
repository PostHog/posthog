from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.hogql.errors import QueryError

from posthog.errors import CHQueryErrorS3Error
from posthog.models.exported_asset import ExportedAsset
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.temporal.common.slo_interceptor import SloInterceptor
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

EXPORT_FORMAT = ExportedAsset.ExportFormat.PNG


async def _run_export_workflow(env, asset, team, mock_exporter, fake_export):
    mock_exporter.export_asset_direct = fake_export

    async with Worker(
        env.client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[ExportAssetWorkflow],
        activities=[export_asset_activity],
        interceptors=[SloInterceptor()],
        workflow_runner=UnsandboxedWorkflowRunner(),
        activity_executor=ThreadPoolExecutor(max_workers=5),
        debug_mode=True,
    ):
        await env.client.execute_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.id,
                team_id=team.id,
                export_format=EXPORT_FORMAT,
                slo=SloConfig(
                    operation=SloOperation.EXPORT,
                    area=SloArea.ANALYTIC_PLATFORM,
                    team_id=team.id,
                    resource_id=str(asset.id),
                    distinct_id=str(team.id),
                ),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )


def _get_slo_completed_props(mock_analytics) -> dict:
    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    return completed_calls[0].kwargs["properties"]


def _success_export(asset_obj, **kwargs):
    asset_obj.content_location = "s3://bucket/test.png"
    asset_obj.save(update_fields=["content_location"])


@patch("posthog.slo.events.posthoganalytics")
@patch("posthog.temporal.exports.activities.exporter")
async def test_successful_export(
    mock_exporter: MagicMock,
    mock_analytics: MagicMock,
    team,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(team=team, export_format=EXPORT_FORMAT)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _run_export_workflow(env, asset, team, mock_exporter, _success_export)

    await sync_to_async(asset.refresh_from_db)()
    assert asset.has_content

    props = _get_slo_completed_props(mock_analytics)
    assert props["outcome"] == SloOutcome.SUCCESS
    assert props["operation"] == "export"
    assert props["resource_id"] == str(asset.id)
    assert props["export_format"] == EXPORT_FORMAT
    assert "error" not in props


@patch("posthog.slo.events.posthoganalytics")
@patch("posthog.temporal.exports.activities.exporter")
async def test_transient_error_retries_and_succeeds(
    mock_exporter: MagicMock,
    mock_analytics: MagicMock,
    team,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(team=team, export_format=EXPORT_FORMAT)

    call_count = 0

    def flaky_export(asset_obj, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise CHQueryErrorS3Error("S3 error", code=499)
        _success_export(asset_obj, **kwargs)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _run_export_workflow(env, asset, team, mock_exporter, flaky_export)

    assert call_count == 3

    await sync_to_async(asset.refresh_from_db)()
    assert asset.has_content

    props = _get_slo_completed_props(mock_analytics)
    assert props["outcome"] == SloOutcome.SUCCESS
    assert "error" not in props


@pytest.mark.parametrize(
    "error_factory,expected_exception_class,expected_call_count",
    [
        (lambda: QueryError("Invalid HogQL query"), "QueryError", 1),
        (lambda: RuntimeError("Chrome crashed"), "RuntimeError", 1),
        (lambda: CHQueryErrorS3Error("S3 error", code=499), "CHQueryErrorS3Error", 10),
    ],
    ids=["non_retryable_user_error", "generic_runtime_error", "retryable_system_error"],
)
@patch("posthog.slo.events.posthoganalytics")
@patch("posthog.temporal.exports.activities.exporter")
async def test_export_failure_emits_slo_failure(
    mock_exporter: MagicMock,
    mock_analytics: MagicMock,
    team,
    error_factory,
    expected_exception_class: str,
    expected_call_count: int,
):
    asset = await sync_to_async(ExportedAsset.objects.create)(team=team, export_format=EXPORT_FORMAT)

    call_count = 0

    def failing_export(asset_obj, **kwargs):
        nonlocal call_count
        call_count += 1
        raise error_factory()

    with pytest.raises(Exception):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            await _run_export_workflow(env, asset, team, mock_exporter, failing_export)

    assert call_count == expected_call_count

    props = _get_slo_completed_props(mock_analytics)
    assert props["outcome"] == SloOutcome.FAILURE
    assert props["error"] is not None
    assert expected_exception_class in str(props["error"])
