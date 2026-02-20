import time
import typing
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import MetricMeter
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)

EVAL_ACTIVITY_TYPES = {
    "fetch_evaluation_activity",
    "execute_llm_judge_activity",
    "emit_evaluation_event_activity",
    "emit_internal_telemetry_activity",
    "increment_trial_eval_count_activity",
    "update_key_state_activity",
}

EVAL_WORKFLOW_TYPES = {
    "run-evaluation",
}

Attributes = dict[str, str | int | float | bool]


def get_metric_meter(additional_attributes: Attributes | None = None) -> MetricMeter:
    """Return a meter depending on in which context we are."""
    if activity.in_activity():
        meter = activity.metric_meter()
    elif workflow.in_workflow():
        meter = workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")

    if additional_attributes:
        meter = meter.with_additional_attributes(additional_attributes)

    return meter


def increment_workflow_started() -> None:
    """Track workflow starts."""
    meter = get_metric_meter()
    counter = meter.create_counter("llma_eval_workflow_started", "Number of eval workflows started")
    counter.add(1)


def increment_workflow_finished(status: str) -> None:
    """Track workflow completions by outcome (completed/failed/skipped)."""
    meter = get_metric_meter({"status": status})
    counter = meter.create_counter("llma_eval_workflow_finished", "Number of eval workflows finished")
    counter.add(1)


def increment_verdict(verdict: str) -> None:
    """Track verdict distribution (true/false/na/error)."""
    meter = get_metric_meter({"verdict": verdict})
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


def increment_errors(error_type: str) -> None:
    """Track error categorization. Safe to call outside Temporal context (no-ops)."""
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"error_type": error_type})
    counter = meter.create_counter("llma_eval_errors", "Error counts by type")
    counter.add(1)


def increment_tokens(token_type: str, count: int) -> None:
    """Track token usage (input/output/total)."""
    meter = get_metric_meter({"token_type": token_type})
    counter = meter.create_counter("llma_eval_tokens", "Token usage")
    counter.add(count)


def record_schedule_to_start_latency(activity_type: str, latency_ms: int) -> None:
    """Record queue depth indicator for alerting."""
    meter = get_metric_meter({"activity_type": activity_type})
    hist = meter.create_histogram_timedelta(
        name="llma_eval_activity_schedule_to_start_latency",
        description="Time between activity scheduling and start (queue depth indicator)",
        unit="ms",
    )
    hist.record(dt.timedelta(milliseconds=latency_ms))


class ExecutionTimeRecorder:
    """Context manager to record execution time to a histogram metric."""

    def __init__(
        self,
        histogram_name: str,
        /,
        description: str | None = None,
        histogram_attributes: Attributes | None = None,
        log: bool = False,
    ) -> None:
        self.histogram_name = histogram_name
        self.description = description
        self.histogram_attributes = histogram_attributes or {}
        self.log = log
        self._start_counter: float | None = None
        self._status_override: str | None = None

    def set_status(self, status: str) -> None:
        """Override the status that will be recorded. Use for non-exception outcomes like SKIPPED."""
        self._status_override = status

    def __enter__(self) -> typing.Self:
        self._start_counter = time.perf_counter()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback) -> None:
        if not self._start_counter:
            raise RuntimeError("Start counter not initialized, did you call `__enter__`?")

        end_counter = time.perf_counter()
        delta_milli_seconds = int((end_counter - self._start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_milli_seconds)

        attributes = dict(self.histogram_attributes)

        if exc_value is not None:
            attributes["status"] = "FAILED"
            attributes["exception"] = str(exc_value)
        elif self._status_override is not None:
            attributes["status"] = self._status_override
            attributes["exception"] = ""
        else:
            attributes["status"] = "COMPLETED"
            attributes["exception"] = ""

        meter = get_metric_meter(attributes)
        hist = meter.create_histogram_timedelta(name=self.histogram_name, description=self.description, unit="ms")
        try:
            hist.record(value=delta)
        except Exception:
            LOGGER.exception("Failed to record execution time to histogram '%s'", self.histogram_name)

        if self.log:
            LOGGER.info(
                "Finished %s with status '%s' in %dms",
                self.histogram_name,
                attributes["status"],
                delta_milli_seconds,
            )

        self._start_counter = None


class EvalsMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for evals workflows."""

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

                # Check if workflow was skipped
                if isinstance(result, dict) and result.get("skipped"):
                    status = "SKIPPED"
                    recorder.set_status(status)
                    increment_workflow_finished(status)
                    return result

                # Record verdict
                if isinstance(result, dict):
                    verdict = result.get("verdict")
                    if verdict is True:
                        increment_verdict("true")
                    elif verdict is False:
                        increment_verdict("false")
                    elif verdict is None:
                        # N/A case (applicable=false)
                        increment_verdict("na")

                increment_workflow_finished(status)
                return result

            except Exception:
                status = "FAILED"
                increment_workflow_finished(status)
                increment_errors("workflow_exception")
                raise
