import json
import dataclasses
from datetime import timedelta

import temporalio.workflow as wf

from posthog.event_usage import EventSource
from posthog.slo.types import SloConfig, SloOutcome
from posthog.tasks.exports.failure_handler import is_user_query_error_type
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import resolve_exception_class
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import ExportAssetActivityInputs


@dataclasses.dataclass
class ExportAssetWorkflowInputs:
    exported_asset_id: int
    team_id: int
    distinct_id: str = ""
    slo: SloConfig | None = None


@wf.defn(name="export-asset")
class ExportAssetWorkflow(PostHogWorkflow):
    """One-off export workflow: export a single asset with durable retry."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExportAssetWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExportAssetWorkflowInputs(**loaded)

    @wf.run
    async def run(self, inputs: ExportAssetWorkflowInputs) -> None:
        try:
            await wf.execute_activity(
                export_asset_activity,
                ExportAssetActivityInputs(
                    exported_asset_id=inputs.exported_asset_id,
                    source=EventSource.EXPORT,
                ),
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=EXPORT_RETRY_POLICY,
            )
        except Exception as e:
            # User-query failures aren't an SLO breach -> reclassify as SUCCESS
            if inputs.slo and is_user_query_error_type(resolve_exception_class(e)):
                inputs.slo.outcome = SloOutcome.SUCCESS
            raise
