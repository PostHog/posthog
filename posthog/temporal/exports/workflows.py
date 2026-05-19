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
from posthog.temporal.exports.types import ExportAssetActivityInputs, ExportAssetResult, ExportError


@dataclasses.dataclass
class ExportAssetWorkflowInputs:
    exported_asset_id: int
    team_id: int
    distinct_id: str = ""
    slo: SloConfig | None = None


def _apply_user_error_to_slo(slo: SloConfig, error: ExportError) -> None:
    """Populate SLO completion properties for a user-query failure returned
    (not raised) by `export_asset_activity`. The SLO interceptor only sees an
    exception on the system-error path, so user errors are invisible to it —
    set the same `error_*` fields here to keep observability parity, and pin
    the outcome to SUCCESS (user query bugs aren't an infra breach).
    """
    slo.outcome = SloOutcome.SUCCESS
    slo.completion_properties.setdefault("error_type", error.exception_class)
    # Match the canonical "<type>: <message>" rendering produced by
    # `str(ApplicationError)`, so user-error and system-error paths emit the
    # same `error_message` shape (see test_export_failure_emits_slo_outcome).
    formatted_message = (
        f"{error.exception_class}: {error.error_message}" if error.error_message else error.exception_class
    )
    slo.completion_properties.setdefault("error_message", formatted_message)
    slo.completion_properties.setdefault("error_trace", error.error_trace)


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
            result: ExportAssetResult = await wf.execute_activity(
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

        # User-query failures are returned (not raised) by the activity so the
        # activity-level error tracking interceptor doesn't capture them. The
        # SLO interceptor never sees the exception, so populate completion
        # properties here to keep the emitted SLO event consistent with the
        # raised-exception path. The asset's `exception`, `exception_type`,
        # and `failure_type` fields are already populated by
        # `_record_export_failure` before the activity returned.
        if inputs.slo and not result.success and result.error is not None:
            _apply_user_error_to_slo(inputs.slo, result.error)
