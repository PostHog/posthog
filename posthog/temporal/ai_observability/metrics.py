import typing
import datetime as dt

from django.conf import settings

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.logger import get_write_only_logger

# Generic temporal metric helpers live in common so other subsystems (e.g. session-replay
# delete-recordings) can import them without pulling this package's eager worker registration.
from posthog.temporal.common.metrics import Attributes, ExecutionTimeRecorder, get_metric_meter

__all__ = ["Attributes", "ExecutionTimeRecorder", "get_metric_meter"]

LOGGER = get_write_only_logger(__name__)

EVAL_ACTIVITY_TYPES = {
    "fetch_evaluation_activity",
    "execute_llm_judge_activity",
    "execute_hog_eval_activity",
    "execute_sentiment_eval_activity",
    "emit_evaluation_event_activity",
    "emit_internal_telemetry_activity",
    "increment_trial_eval_count_activity",
    "send_trial_usage_email_activity",
    "update_key_state_activity",
    "emit_eval_signal_activity",
}

EVAL_WORKFLOW_TYPES = {
    "run-evaluation",
}


def increment_workflow_started() -> None:
    """Track workflow starts."""
    meter = get_metric_meter()
    counter = meter.create_counter("llma_eval_workflow_started", "Number of eval workflows started")
    counter.add(1)


def increment_workflow_finished(status: str, evaluation_type: str = "llm_judge") -> None:
    """Track workflow completions by outcome (completed/failed/skipped)."""
    meter = get_metric_meter({"status": status, "evaluation_type": evaluation_type})
    counter = meter.create_counter("llma_eval_workflow_finished", "Number of eval workflows finished")
    counter.add(1)


def increment_verdict(verdict: str, evaluation_type: str = "llm_judge") -> None:
    """Track verdict distribution (true/false/na/error)."""
    meter = get_metric_meter({"verdict": verdict, "evaluation_type": evaluation_type})
    counter = meter.create_counter("llma_eval_verdict", "Verdict distribution")
    counter.add(1)


def increment_key_type(key_type: str) -> None:
    """Track BYOK vs PostHog trial usage."""
    meter = get_metric_meter({"key_type": key_type})
    counter = meter.create_counter("llma_eval_key_type", "API key type usage")
    counter.add(1)


def increment_provider_model(provider: str, model: str) -> None:
    """Track provider/model breakdown."""
    meter = get_metric_meter({"provider": provider, "model": model})
    counter = meter.create_counter("llma_eval_provider_model", "Provider and model usage")
    counter.add(1)


def increment_errors(error_type: str, *, provider: str | None = None) -> None:
    """Track error categorization. Safe to call outside Temporal context (no-ops).

    Pass `provider` so dashboards can isolate a single misbehaving upstream
    (e.g. an OpenAI 5xx storm) without grepping logs.
    """
    if not activity.in_activity() and not workflow.in_workflow():
        return
    attrs: dict[str, str | int | float | bool] = {"error_type": error_type}
    if provider is not None:
        attrs["provider"] = provider
    meter = get_metric_meter(attrs)
    counter = meter.create_counter("llma_eval_errors", "Error counts by type")
    counter.add(1)


def increment_user_errors(error_type: str, *, provider: str | None = None) -> None:
    """Track terminal user-actionable eval errors separately from system failures."""
    if not activity.in_activity() and not workflow.in_workflow():
        return
    attrs: dict[str, str | int | float | bool] = {"error_type": error_type}
    if provider is not None:
        attrs["provider"] = provider
    meter = get_metric_meter(attrs)
    counter = meter.create_counter("llma_eval_user_errors", "Terminal user-actionable evaluation errors")
    counter.add(1)


def increment_eval_signal_outcome(outcome: str) -> None:
    """Track eval signal activity outcomes (skipped_config_disabled, skipped_org_not_approved, skipped_low_significance, emitted, summarization_failed)."""
    meter = get_metric_meter({"outcome": outcome})
    counter = meter.create_counter("llma_eval_signal_outcome", "Eval signal activity outcome distribution")
    counter.add(1)


def increment_tokens(token_type: str, count: int) -> None:
    """Track token usage (input/output/total)."""
    meter = get_metric_meter({"token_type": token_type})
    counter = meter.create_counter("llma_eval_tokens", "Token usage")
    counter.add(count)


def increment_emit_event_outcome(outcome: str) -> None:
    """Track $ai_evaluation event emission outcomes (success/failed).

    Distinguishes Activity 4 failures from other workflow failures so we can
    measure and alert on dropped eval events specifically.
    """
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"outcome": outcome})
    counter = meter.create_counter(
        "llma_eval_emit_event_outcome",
        "Outcome of $ai_evaluation event emission (success/failed)",
    )
    counter.add(1)


def record_schedule_to_start_latency(activity_type: str, latency_ms: int) -> None:
    """Record queue depth indicator for alerting."""
    meter = get_metric_meter({"activity_type": activity_type})
    hist = meter.create_histogram_timedelta(
        name="llma_eval_activity_schedule_to_start_latency",
        description="Time between activity scheduling and start (queue depth indicator)",
        unit="ms",
    )
    hist.record(dt.timedelta(milliseconds=latency_ms))


class EvalsMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for evals workflows."""

    task_queue = settings.LLMA_EVALS_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _EvalsMetricsActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _EvalsMetricsWorkflowInterceptor


class _EvalsMetricsActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in EVAL_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Record schedule-to-start latency (queue depth indicator)
        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            record_schedule_to_start_latency(activity_type, schedule_to_start_ms)

        histogram_attributes: Attributes = {"activity_type": activity_type}

        with ExecutionTimeRecorder(
            "llma_eval_activity_execution_latency",
            description="Execution latency for eval activities",
            histogram_attributes=histogram_attributes,
        ):
            return await super().execute_activity(input)


class _EvalsMetricsWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()
        workflow_type = workflow_info.workflow_type

        if workflow_type not in EVAL_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        increment_workflow_started()

        with ExecutionTimeRecorder(
            "llma_eval_workflow_execution_latency",
            description="End-to-end workflow execution latency",
        ) as recorder:
            status = "COMPLETED"
            try:
                result = await super().execute_workflow(input)

                # Extract evaluation_type for metric labeling
                evaluation_type = "llm_judge"
                if isinstance(result, dict):
                    evaluation_type = result.get("evaluation_type", "llm_judge")

                # Check if workflow was skipped
                if isinstance(result, dict) and result.get("skipped"):
                    status = "SKIPPED"
                    recorder.set_status(status)
                    increment_workflow_finished(status, evaluation_type)
                    return result

                # Record verdict for boolean-output evaluations. Sentiment emits no boolean verdict.
                if isinstance(result, dict) and "verdict" in result:
                    verdict = result.get("verdict")
                    if verdict is True:
                        increment_verdict("true", evaluation_type)
                    elif verdict is False:
                        increment_verdict("false", evaluation_type)
                    elif verdict is None:
                        # N/A case (applicable=false)
                        increment_verdict("na", evaluation_type)

                increment_workflow_finished(status, evaluation_type)
                return result

            except Exception:
                status = "FAILED"
                increment_workflow_finished(status)
                raise
