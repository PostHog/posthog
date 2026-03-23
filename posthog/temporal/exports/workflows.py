import traceback
import dataclasses
from datetime import timedelta
from typing import Optional

import temporalio.workflow as wf
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.slo.types import SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import EmitExportOutcomeInput, ExportAssetActivityInputs, ExportError

with wf.unsafe.imports_passed_through():
    from posthog.temporal.exports.activities import emit_export_outcome, export_asset_activity


@dataclasses.dataclass
class ExportAssetWorkflowInputs:
    exported_asset_id: int
    team_id: int
    distinct_id: str = ""
    source: Optional[str] = None
    export_format: Optional[str] = None


@wf.defn(name="export-asset")
class ExportAssetWorkflow(PostHogWorkflow):
    """One-off export workflow: export a single asset with durable retry, then emit SLO outcome."""

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
                    source=inputs.source,
                ),
                retry_policy=EXPORT_RETRY_POLICY,
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=2),
            )

        except (ActivityError, ApplicationError) as e:
            outcome = SloOutcome.FAILURE
            caught_error = e
            cause = e.cause if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError) else e
            if isinstance(cause, ApplicationError) and cause.details:
                error = ExportError(
                    exception_class=cause.details[0] if len(cause.details) >= 1 else type(e).__name__,
                    error_trace=cause.details[4] if len(cause.details) >= 5 else "",
                )
            else:
                error = ExportError(exception_class=type(e).__name__, error_trace=str(e))

        except Exception as e:
            outcome = SloOutcome.FAILURE
            caught_error = e
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
                    distinct_id=inputs.distinct_id or str(inputs.team_id),
                    outcome=outcome,
                    duration_ms=duration_ms,
                    export_format=inputs.export_format or "",
                    source=inputs.source or "",
                    error=error,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        # Re-raise after SLO event is emitted so Temporal marks the workflow as failed
        if caught_error is not None:
            raise caught_error
