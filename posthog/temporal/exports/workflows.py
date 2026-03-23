import json
import traceback
import dataclasses
from datetime import timedelta
from typing import Optional

import temporalio.workflow as wf
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.event_usage import EventSource
from posthog.slo.types import SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.activities import emit_export_outcome, export_asset_activity
from posthog.temporal.exports.types import EmitExportOutcomeInput, ExportAssetActivityInputs, ExportError


@dataclasses.dataclass
class ExportAssetWorkflowInputs:
    exported_asset_id: int
    team_id: int
    distinct_id: str = ""
    export_format: Optional[str] = None


@wf.defn(name="export-asset")
class ExportAssetWorkflow(PostHogWorkflow):
    """One-off export workflow: export a single asset with durable retry."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExportAssetWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExportAssetWorkflowInputs(**loaded)

    @wf.run
    async def run(self, inputs: ExportAssetWorkflowInputs) -> None:
        start_time = wf.time()
        outcome = SloOutcome.SUCCESS
        error: Optional[ExportError] = None
        caught_error: BaseException | None = None

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
            outcome = SloOutcome.FAILURE
            caught_error = e

            # Unwrap Temporal's ActivityError -> ApplicationError chain to get structured details
            cause = e.cause if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError) else None
            if isinstance(cause, ApplicationError) and cause.details:
                error = ExportError(
                    exception_class=cause.details[0] if len(cause.details) >= 1 else type(e).__name__,
                    error_trace=cause.details[4] if len(cause.details) >= 5 else "",
                )
            else:
                error = ExportError(
                    exception_class=type(e).__name__,
                    error_trace="\n".join(traceback.format_exception(e)[:5]),
                )

        finally:
            duration_ms = (wf.time() - start_time) * 1000
            await wf.execute_activity(
                emit_export_outcome,
                EmitExportOutcomeInput(
                    exported_asset_id=inputs.exported_asset_id,
                    team_id=inputs.team_id,
                    distinct_id=inputs.distinct_id,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    export_format=inputs.export_format,
                    error=error,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
                ),
            )

        # Re-raise after SLO event is emitted so Temporal marks the workflow as failed
        if caught_error is not None:
            raise caught_error
