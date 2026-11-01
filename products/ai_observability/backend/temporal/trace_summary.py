from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.ph_client import ph_background_capture
    from posthog.temporal.ai_observability.retries import is_last_attempt
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.utils import on_asyncify_pool

    from ..facade import api
    from ..facade.contracts import TraceSummaryJob
    from ..logic.traces.summary import (
        ATTEMPT_DEADLINE,
        FAIL_DEADLINE,
        HEARTBEAT_TIMEOUT,
        JOB_DEADLINE,
        MAX_ATTEMPTS,
        RETRY_BACKOFF,
        RETRY_INITIAL_INTERVAL,
        RETRY_MAX_INTERVAL,
    )
    from .trace_summary_client import TRACE_SUMMARY_WORKFLOW_NAME

GENERATE_TRACE_SUMMARY_ACTIVITY_NAME = "ai-observability-generate-trace-summary"
FAIL_TRACE_SUMMARY_ACTIVITY_NAME = "ai-observability-fail-trace-summary"


@activity.defn(name=GENERATE_TRACE_SUMMARY_ACTIVITY_NAME)
async def generate_trace_summary_activity(job: TraceSummaryJob) -> None:
    async with Heartbeater():
        run = await on_asyncify_pool(api.generate_trace_summary)(job, final_attempt=is_last_attempt())
    if run is None:
        return
    properties: dict[str, object] = {
        "duration_ms": run.duration_ms,
        "input_characters": run.input_characters,
        "model": run.model,
        "was_sampled": run.was_sampled,
    }
    if run.status == "failed":
        properties["failure_reason"] = run.failure_reason
    ph_background_capture()(
        distinct_id=run.distinct_id,
        event=f"llma trace view summary {'completed' if run.status == 'ready' else 'failed'}",
        properties=properties,
        groups=run.groups,
    )


@activity.defn(name=FAIL_TRACE_SUMMARY_ACTIVITY_NAME)
async def fail_trace_summary_activity(job: TraceSummaryJob) -> None:
    await on_asyncify_pool(api.fail_trace_summary)(job)


@workflow.defn(name=TRACE_SUMMARY_WORKFLOW_NAME)
class TraceSummaryWorkflow(PostHogWorkflow):
    inputs_cls = TraceSummaryJob

    @workflow.run
    async def run(self, job: TraceSummaryJob) -> None:
        try:
            await workflow.execute_activity(
                generate_trace_summary_activity,
                job,
                start_to_close_timeout=ATTEMPT_DEADLINE,
                schedule_to_close_timeout=JOB_DEADLINE,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(
                    maximum_attempts=MAX_ATTEMPTS,
                    initial_interval=RETRY_INITIAL_INTERVAL,
                    backoff_coefficient=RETRY_BACKOFF,
                    maximum_interval=RETRY_MAX_INTERVAL,
                ),
            )
        except ActivityError:
            # The last attempt raised or timed out before writing a result, so the entry would stay pending.
            await workflow.execute_activity(
                fail_trace_summary_activity,
                job,
                start_to_close_timeout=FAIL_DEADLINE / 4,
                schedule_to_close_timeout=FAIL_DEADLINE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
