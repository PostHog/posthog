import json
import dataclasses
from datetime import timedelta

import temporalio.workflow as wf
from temporalio.common import RetryPolicy

from posthog.event_usage import EventSource
from posthog.slo.types import SloConfig, SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import resolve_exception_class, unwrap_temporal_cause
from posthog.temporal.exports.activities import export_asset_activity, record_export_failure_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import ExportAssetActivityInputs, RecordExportFailureInputs

from products.exports.backend.tasks.failure_handler import is_user_query_error_type

# Shown to the user when the export failed but no in-process exception was recorded — i.e. the
# worker timed out or was killed before it could persist a specific error.
DEFAULT_EXPORT_FAILURE_MESSAGE = (
    "Export failed to complete. The query may have timed out, or the worker was interrupted "
    "before finishing. Please try running the export again."
)


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
            exception_type = resolve_exception_class(e)

            # The activity has exhausted its retries, so the export is terminally failed. Persist
            # that onto the asset (idempotently) so it's never left silently empty — a worker that
            # was killed before its in-process handler ran would otherwise leave no exception, and
            # the download endpoint could only surface that as a bare 404. Uses its own retry policy;
            # a failure to record must not mask the original error.
            cause = unwrap_temporal_cause(e)
            message = cause.message if cause is not None and cause.message else DEFAULT_EXPORT_FAILURE_MESSAGE
            try:
                await wf.execute_activity(
                    record_export_failure_activity,
                    RecordExportFailureInputs(
                        exported_asset_id=inputs.exported_asset_id,
                        message=message,
                        exception_type=exception_type,
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                wf.logger.warning("Failed to record terminal export failure", exc_info=True)

            # User-query failures aren't an SLO breach -> reclassify as SUCCESS
            if inputs.slo and is_user_query_error_type(exception_type):
                inputs.slo.outcome = SloOutcome.SUCCESS
            raise
