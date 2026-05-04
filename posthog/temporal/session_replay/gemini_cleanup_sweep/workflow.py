from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import (
    SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
    SWEEP_ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import CleanupSweepInputs

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.session_replay.gemini_cleanup_sweep.activities import sweep_gemini_files_activity


@workflow.defn(name=WORKFLOW_NAME)
class GeminiFileCleanupSweepWorkflow(PostHogWorkflow):
    inputs_cls = CleanupSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: CleanupSweepInputs) -> dict[str, Any]:
        result = await workflow.execute_activity(
            sweep_gemini_files_activity,
            inputs,
            start_to_close_timeout=SWEEP_ACTIVITY_TIMEOUT,
            heartbeat_timeout=SWEEP_ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return {
            "listed": result.listed,
            "deleted": result.deleted,
            "skipped_running": result.skipped_running,
            "skipped_too_young": result.skipped_too_young,
            "skipped_unrecognized_prefix": result.skipped_unrecognized_prefix,
            "skipped_no_name": result.skipped_no_name,
            "skipped_temporal_error": result.skipped_temporal_error,
            "delete_failed": result.delete_failed,
            "hit_max_files_cap": result.hit_max_files_cap,
        }
