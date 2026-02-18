"""Prometheus metrics for the LLMA trace summarization temporal workflows.

Follows the same pattern as posthog.temporal.llm_analytics.metrics (evals).
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
# Activity / workflow type sets for the interceptor
# ---------------------------------------------------------------------------

SUMMARIZATION_ACTIVITY_TYPES = {
    "sample_items_in_window_activity",
    "fetch_and_format_activity",
    "summarize_and_save_activity",
}

SUMMARIZATION_WORKFLOW_TYPES = {
    "llma-trace-summarization",
}

# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------


def increment_workflow_started(analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_summarization_workflow_started",
        "Summarization workflows started",
    ).add(1)


def increment_workflow_finished(status: str, analysis_level: str) -> None:
    meter = get_metric_meter({"status": status, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_summarization_workflow_finished",
        "Summarization workflows finished",
    ).add(1)


def record_items_sampled(count: int, analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_summarization_items_sampled",
        "Items sampled for summarization",
    ).add(count)


def increment_item_result(outcome: str, analysis_level: str) -> None:
    """Track per-item outcome: generated / failed / skipped."""
    meter = get_metric_meter({"outcome": outcome, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_summarization_items_processed",
        "Items processed by outcome",
    ).add(1)


def increment_skip(reason: str, analysis_level: str) -> None:
    meter = get_metric_meter({"reason": reason, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_summarization_skips",
        "Items skipped by reason",
    ).add(1)


def increment_embedding_result(outcome: str) -> None:
    """outcome: succeeded / failed."""
    meter = get_metric_meter({"outcome": outcome})
    meter.create_counter(
        "llma_summarization_embeddings",
        "Embedding requests by outcome",
    ).add(1)


def increment_errors(error_type: str) -> None:
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"error_type": error_type})
    meter.create_counter(
        "llma_summarization_errors",
        "Error counts by type",
    ).add(1)


# ---------------------------------------------------------------------------
# Interceptor — automatic timing for activities and workflows
# ---------------------------------------------------------------------------


class SummarizationMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for summarization workflows."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _SummarizationActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _SummarizationWorkflowInterceptor


class _SummarizationActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in SUMMARIZATION_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Schedule-to-start latency (queue depth indicator)
        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            meter = get_metric_meter({"activity_type": activity_type})
            meter.create_histogram_timedelta(
                name="llma_summarization_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(dt.timedelta(milliseconds=schedule_to_start_ms))

        with ExecutionTimeRecorder(
            "llma_summarization_activity_execution_latency",
            description="Execution latency for summarization activities",
            histogram_attributes={"activity_type": activity_type},
        ):
            return await super().execute_activity(input)


class _SummarizationWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()

        if workflow_info.workflow_type not in SUMMARIZATION_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        with ExecutionTimeRecorder(
            "llma_summarization_workflow_execution_latency",
            description="End-to-end workflow execution latency",
        ):
            return await super().execute_workflow(input)
