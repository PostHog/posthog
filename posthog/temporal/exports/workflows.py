import json
import dataclasses
from datetime import timedelta

import temporalio.workflow as wf

from posthog.event_usage import EventSource
from posthog.slo.types import SloConfig, SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import resolve_exception_class
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import ExportAssetActivityInputs, extract_error_details, is_user_query_export_error

from products.exports.backend.tasks.failure_handler import is_user_query_error_type


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
            if inputs.slo:
                failure = extract_error_details(e)
                is_user_query_error = (
                    is_user_query_export_error(failure)
                    if failure is not None
                    else is_user_query_error_type(resolve_exception_class(e))
                )
                if is_user_query_error:
                    inputs.slo.outcome = SloOutcome.SUCCESS
                else:
                    if failure and failure.failure_details:
                        inputs.slo.completion_properties.update(failure.failure_details)
                    inputs.slo.completion_properties["failure_stage"] = "asset_generation"
            raise
