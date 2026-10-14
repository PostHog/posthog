import json
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app.activities.unfurl_charts import (
    post_slack_unfurl_charts_activity,
    prepare_slack_unfurl_charts_activity,
)
from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

from products.exports.backend.facade.api import RENDER_TIMEOUT

SLACK_APP_UNFURL_CHARTS_WORKFLOW_TIMEOUT = timedelta(minutes=5)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))


@workflow.defn(name="slack-app-unfurl-charts")
class SlackAppUnfurlChartsWorkflow(PostHogWorkflow):
    """Render the insights in a link unfurl and post the cards again with their charts."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppUnfurlChartsWorkflowInputs:
        return SlackAppUnfurlChartsWorkflowInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SlackAppUnfurlChartsWorkflowInputs) -> None:
        prepared = await workflow.execute_activity(
            prepare_slack_unfurl_charts_activity,
            inputs,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )
        rendered = [asset for asset in prepared.assets if asset.cached]
        failed_count = prepared.refused_count
        to_render = [asset for asset in prepared.assets if not asset.cached]
        results = await asyncio.gather(
            *(self._render(inputs, prepared, asset) for asset in to_render),
            return_exceptions=True,
        )
        for asset, result in zip(to_render, results):
            if isinstance(result, BaseException):
                failed_count += 1
                workflow.logger.warning(
                    "slack_app_unfurl_chart_render_failed",
                    extra={"asset_id": asset.asset_id, "error": str(result)},
                )
            else:
                rendered.append(asset)

        await workflow.execute_activity(
            post_slack_unfurl_charts_activity,
            SlackAppUnfurlChartsPostInput(
                request=inputs,
                rendered=rendered,
                failed_count=failed_count,
                elapsed_ms=int((workflow.now() - workflow.info().start_time).total_seconds() * 1000),
            ),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY_POLICY,
        )

    async def _render(
        self,
        inputs: SlackAppUnfurlChartsWorkflowInputs,
        prepared: SlackAppUnfurlChartsPrepared,
        asset: SlackUnfurlChartAsset,
    ) -> None:
        # A child workflow, so no worker waits while the export renders.
        await workflow.execute_child_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.asset_id,
                team_id=inputs.team_id,
                distinct_id=prepared.distinct_id,
            ),
            id=f"export-asset-{asset.asset_id}",
            task_queue=inputs.export_task_queue,
            execution_timeout=RENDER_TIMEOUT,
        )
