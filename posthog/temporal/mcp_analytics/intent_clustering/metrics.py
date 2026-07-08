"""Prometheus metrics for the MCP analytics intent clustering workflow.

Pattern lifted from
``posthog/temporal/ai_observability/trace_clustering/metrics.py`` — same
shape of counters (started/finished/errors, items/clusters analysed) and
histograms (workflow execution latency, activity execution latency,
schedule-to-start latency).

Metrics are emitted by ``ClusteringMetricsInterceptor`` automatically for
the workflow/activity types listed below; helper functions are also
exposed so the activity can record domain-specific counters from inside
its body.
"""

import typing

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

from posthog.temporal.ai_observability.metrics import ExecutionTimeRecorder, get_metric_meter
from posthog.temporal.mcp_analytics.intent_clustering.constants import COORDINATOR_WORKFLOW_NAME, WORKFLOW_NAME

# Histograms registered into PrometheusConfig via common/worker.py.
MCPA_CLUSTERING_LATENCY_HISTOGRAM_METRICS = (
    "mcpa_clustering_activity_execution_latency",
    "mcpa_clustering_activity_schedule_to_start_latency",
    "mcpa_clustering_workflow_execution_latency",
)
MCPA_CLUSTERING_LATENCY_HISTOGRAM_BUCKETS = [
    1_000.0,  # 1s
    5_000.0,  # 5s
    10_000.0,  # 10s
    30_000.0,  # 30s
    60_000.0,  # 1m
    120_000.0,  # 2m
    300_000.0,  # 5m
    600_000.0,  # 10m
    900_000.0,  # 15m
    1_800_000.0,  # 30m
]

# Activity / workflow type sets the interceptor recognises.
MCPA_CLUSTERING_ACTIVITY_TYPES = {
    "compute_intent_clusters_activity",
    "get_team_ids_for_mcp_analytics",
}

MCPA_CLUSTERING_WORKFLOW_TYPES = {
    WORKFLOW_NAME,
    COORDINATOR_WORKFLOW_NAME,
}


# Counter helpers ---------------------------------------------------------


def increment_workflow_started(workflow_type: str) -> None:
    meter = get_metric_meter({"workflow_type": workflow_type})
    meter.create_counter("mcpa_clustering_workflow_started", "Intent clustering workflows started").add(1)


def increment_workflow_finished(status: str, workflow_type: str) -> None:
    meter = get_metric_meter({"status": status, "workflow_type": workflow_type})
    meter.create_counter("mcpa_clustering_workflow_finished", "Intent clustering workflows finished").add(1)


def record_intents_analyzed(count: int) -> None:
    meter = get_metric_meter()
    meter.create_counter("mcpa_clustering_intents_analyzed", "Intents fed into clustering").add(count)


def record_clusters_generated(count: int) -> None:
    meter = get_metric_meter()
    meter.create_counter("mcpa_clustering_clusters_generated", "Clusters produced").add(count)


def increment_errors(error_type: str) -> None:
    # Only safe to call inside a worker context.
    if not activity.in_activity() and not workflow.in_workflow():
        return
    meter = get_metric_meter({"error_type": error_type})
    meter.create_counter("mcpa_clustering_errors", "Errors by exception type").add(1)


# Interceptor -------------------------------------------------------------


class MCPAClusteringMetricsInterceptor(Interceptor):
    """Intercepts MCPA clustering workflows + activities to emit Prometheus metrics."""

    task_queue = settings.MCPA_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _MCPAClusteringActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _MCPAClusteringWorkflowInterceptor


class _MCPAClusteringActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in MCPA_CLUSTERING_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        # Schedule-to-start latency (queue depth indicator).
        scheduled = activity_info.scheduled_time
        started = activity_info.started_time
        if scheduled and started:
            meter = get_metric_meter({"activity_type": activity_type})
            meter.create_histogram_timedelta(
                name="mcpa_clustering_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(started - scheduled)

        with ExecutionTimeRecorder(
            "mcpa_clustering_activity_execution_latency",
            description="Execution latency for MCPA clustering activities",
            histogram_attributes={"activity_type": activity_type},
        ):
            # Don't increment_errors here — the same exception propagates to the
            # workflow interceptor and would double-count. Matches the
            # trace_clustering precedent (error tracking at workflow scope only).
            return await super().execute_activity(input)


class _MCPAClusteringWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        info = workflow.info()
        if info.workflow_type not in MCPA_CLUSTERING_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        increment_workflow_started(info.workflow_type)
        with ExecutionTimeRecorder(
            "mcpa_clustering_workflow_execution_latency",
            description="End-to-end workflow execution latency for MCPA clustering",
            histogram_attributes={"workflow_type": info.workflow_type},
        ):
            try:
                result = await super().execute_workflow(input)
                increment_workflow_finished("completed", info.workflow_type)
                return result
            except Exception as e:
                increment_errors(type(e).__name__)
                increment_workflow_finished("failed", info.workflow_type)
                raise
