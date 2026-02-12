"""Prometheus metrics for the LLMA trace clustering temporal workflows.

Follows the same pattern as trace_summarization/metrics.py.
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

CLUSTERING_LATENCY_HISTOGRAM_METRICS = (
    "llma_clustering_activity_execution_latency",
    "llma_clustering_activity_schedule_to_start_latency",
    "llma_clustering_workflow_execution_latency",
)
CLUSTERING_LATENCY_HISTOGRAM_BUCKETS = [
    1_000.0,  # 1 second
    5_000.0,  # 5 seconds
    10_000.0,  # 10 seconds
    30_000.0,  # 30 seconds
    60_000.0,  # 1 minute
    120_000.0,  # 2 minutes
    300_000.0,  # 5 minutes
    600_000.0,  # 10 minutes
    900_000.0,  # 15 minutes
    1_800_000.0,  # 30 minutes
]

# ---------------------------------------------------------------------------
# Activity / workflow type sets for the interceptor
# ---------------------------------------------------------------------------

CLUSTERING_ACTIVITY_TYPES = {
    "perform_clustering_compute_activity",
    "generate_cluster_labels_activity",
    "emit_cluster_events_activity",
}

CLUSTERING_WORKFLOW_TYPES = {
    "llma-trace-clustering",
}

# ---------------------------------------------------------------------------
# Counter helpers
# ---------------------------------------------------------------------------


def increment_workflow_started(analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_clustering_workflow_started",
        "Clustering workflows started",
    ).add(1)


def increment_workflow_finished(status: str, analysis_level: str) -> None:
    meter = get_metric_meter({"status": status, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_clustering_workflow_finished",
        "Clustering workflows finished",
    ).add(1)


def record_items_analyzed(count: int, analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_clustering_items_analyzed",
        "Items analyzed for clustering",
    ).add(count)


def record_clusters_generated(count: int, analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_clustering_clusters_generated",
        "Clusters generated",
    ).add(count)


def record_noise_points(count: int, analysis_level: str) -> None:
    meter = get_metric_meter({"analysis_level": analysis_level})
    meter.create_counter(
        "llma_clustering_noise_points",
        "Noise points from clustering",
    ).add(count)


def increment_errors(error_type: str) -> None:
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"error_type": error_type})
    meter.create_counter(
        "llma_clustering_errors",
        "Error counts by type",
    ).add(1)


# ---------------------------------------------------------------------------
# Interceptor — automatic timing for activities and workflows
# ---------------------------------------------------------------------------


class ClusteringMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for clustering workflows."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ClusteringActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _ClusteringWorkflowInterceptor


class _ClusteringActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in CLUSTERING_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Schedule-to-start latency (queue depth indicator)
        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            meter = get_metric_meter({"activity_type": activity_type})
            meter.create_histogram_timedelta(
                name="llma_clustering_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(dt.timedelta(milliseconds=schedule_to_start_ms))

        with ExecutionTimeRecorder(
            "llma_clustering_activity_execution_latency",
            description="Execution latency for clustering activities",
            histogram_attributes={"activity_type": activity_type},
        ):
            return await super().execute_activity(input)


class _ClusteringWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()

        if workflow_info.workflow_type not in CLUSTERING_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        # Parse analysis_level from workflow args for metric labels
        analysis_level = "trace"
        if input.args:
            try:
                analysis_level = input.args[0].analysis_level
            except (IndexError, AttributeError):
                pass

        increment_workflow_started(analysis_level)

        with ExecutionTimeRecorder(
            "llma_clustering_workflow_execution_latency",
            description="End-to-end workflow execution latency",
        ):
            try:
                result = await super().execute_workflow(input)
                increment_workflow_finished("completed", analysis_level)
                return result
            except Exception as e:
                increment_errors(type(e).__name__)
                increment_workflow_finished("failed", analysis_level)
                raise
