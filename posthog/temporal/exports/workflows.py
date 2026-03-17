import dataclasses
from datetime import timedelta
from typing import Optional

import temporalio.workflow as wf
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import EmitExportOutcomeInput, ExportAssetActivityInputs, ExportOutcomeAsset

with wf.unsafe.imports_passed_through():
    from posthog.temporal.exports.activities import emit_export_outcome_events, export_asset_activity


@dataclasses.dataclass
class ExportAssetWorkflowInputs:
    exported_asset_id: int
    team_id: int
    source: Optional[str] = None
    export_format: Optional[str] = None
    limit: Optional[int] = None
    max_height_pixels: Optional[int] = None


@wf.defn(name="export-asset")
class ExportAssetWorkflow(PostHogWorkflow):
    """One-off export workflow: export a single asset with durable retry, then emit SLO events."""

    @wf.run
    async def run(self, inputs: ExportAssetWorkflowInputs) -> None:
        result = await wf.execute_activity(
            export_asset_activity,
            ExportAssetActivityInputs(
                exported_asset_id=inputs.exported_asset_id,
                source=inputs.source,
                limit=inputs.limit,
                max_height_pixels=inputs.max_height_pixels,
            ),
            retry_policy=EXPORT_RETRY_POLICY,
            start_to_close_timeout=timedelta(minutes=10),
            schedule_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
        )

        await wf.execute_activity(
            emit_export_outcome_events,
            EmitExportOutcomeInput(
                team_id=inputs.team_id,
                source=inputs.source or "interactive",
                export_format=inputs.export_format or "unknown",
                assets=[
                    ExportOutcomeAsset(
                        exported_asset_id=result.exported_asset_id,
                        success=result.success,
                        failure_type=result.failure_type,
                    )
                ],
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
