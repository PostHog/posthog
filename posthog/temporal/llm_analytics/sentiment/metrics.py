"""Prometheus metrics for the LLMA sentiment classification temporal workflows.

Follows the same pattern as trace_clustering/metrics.py.
Metrics are emitted via Temporal's built-in metric meter (activity/workflow context)
and scraped by the Prometheus endpoint on the worker pod.
"""

import typing
import datetime as dt

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.temporal.llm_analytics.metrics import ExecutionTimeRecorder, get_metric_meter

# ---------------------------------------------------------------------------
# Histogram bucket config (imported by common/worker.py for PrometheusConfig)
# ---------------------------------------------------------------------------

SENTIMENT_LATENCY_HISTOGRAM_METRICS = (
    "llma_sentiment_activity_execution_latency",
    "llma_sentiment_activity_schedule_to_start_latency",
    "llma_sentiment_workflow_execution_latency",
)
SENTIMENT_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,  # 100ms
    500.0,  # 500ms
    1_000.0,  # 1 second
    2_000.0,  # 2 seconds
    5_000.0,  # 5 seconds
    10_000.0,  # 10 seconds
    30_000.0,  # 30 seconds
    60_000.0,  # 1 minute
]

# ---------------------------------------------------------------------------
# Activity / workflow type sets for the interceptor
# ---------------------------------------------------------------------------

SENTIMENT_ACTIVITY_TYPES = {
    "classify_sentiment_activity",
}

SENTIMENT_WORKFLOW_TYPES = {
    "llma-sentiment-classify",
}

# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------


def increment_workflow_started(workflow_type: str) -> None:
    meter = get_metric_meter({"workflow_type": workflow_type})
    meter.create_counter(
        "llma_sentiment_workflow_started",
        "Sentiment workflows started",
    ).add(1)


def increment_workflow_finished(status: str, workflow_type: str) -> None:
    meter = get_metric_meter({"status": status, "workflow_type": workflow_type})
    meter.create_counter(
        "llma_sentiment_workflow_finished",
        "Sentiment workflows finished",
    ).add(1)


def record_traces_classified(count: int) -> None:
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter()
    meter.create_counter(
        "llma_sentiment_traces_classified",
        "Traces classified for sentiment",
    ).add(count)


def record_messages_classified(count: int) -> None:
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter()
    meter.create_counter(
        "llma_sentiment_messages_classified",
        "Messages classified for sentiment",
    ).add(count)


def increment_errors(error_type: str) -> None:
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"error_type": error_type})
    meter.create_counter(
        "llma_sentiment_errors",
        "Error counts by type",
    ).add(1)


# ---------------------------------------------------------------------------
# Interceptor — automatic timing for activities and workflows
# ---------------------------------------------------------------------------


class SentimentMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for sentiment workflows."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _SentimentActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _SentimentWorkflowInterceptor


class _SentimentActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in SENTIMENT_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Schedule-to-start latency (queue depth indicator)
        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            meter = get_metric_meter({"activity_type": activity_type})
            meter.create_histogram_timedelta(
                name="llma_sentiment_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(dt.timedelta(milliseconds=schedule_to_start_ms))

        with ExecutionTimeRecorder(
            "llma_sentiment_activity_execution_latency",
            description="Execution latency for sentiment activities",
            histogram_attributes={"activity_type": activity_type},
        ):
            return await super().execute_activity(input)


class _SentimentWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()
        workflow_type = workflow_info.workflow_type

        if workflow_type not in SENTIMENT_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        increment_workflow_started(workflow_type)

        with ExecutionTimeRecorder(
            "llma_sentiment_workflow_execution_latency",
            description="End-to-end workflow execution latency",
        ):
            try:
                result = await super().execute_workflow(input)
                increment_workflow_finished("completed", workflow_type)
                return result
            except Exception as e:
                increment_errors(type(e).__name__)
                increment_workflow_finished("failed", workflow_type)
                raise
