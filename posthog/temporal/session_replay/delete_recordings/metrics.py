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

from posthog.temporal.llm_analytics.metrics import ExecutionTimeRecorder, get_metric_meter

# ---------------------------------------------------------------------------
# Histogram bucket config (imported by common/worker.py for PrometheusConfig)
# ---------------------------------------------------------------------------

DELETE_RECORDINGS_LATENCY_HISTOGRAM_METRICS = (
    "delete_recordings_activity_execution_latency",
    "delete_recordings_activity_schedule_to_start_latency",
    "delete_recordings_workflow_execution_latency",
)
DELETE_RECORDINGS_LATENCY_HISTOGRAM_BUCKETS = [
    1_000.0,  # 1 second
    5_000.0,  # 5 seconds
    10_000.0,  # 10 seconds
    30_000.0,  # 30 seconds
    60_000.0,  # 1 minute
    120_000.0,  # 2 minutes
    300_000.0,  # 5 minutes
    600_000.0,  # 10 minutes
    1_800_000.0,  # 30 minutes
    3_600_000.0,  # 1 hour
]

# ---------------------------------------------------------------------------
# Activity / workflow type sets for the interceptor
# ---------------------------------------------------------------------------

DELETE_RECORDINGS_ACTIVITY_TYPES = {
    "load-recordings-with-person",
    "load-recordings-with-team-id",
    "load-recordings-with-query",
    "load-session-id-chunk",
    "cleanup-session-id-chunks",
    "delete-recordings",
    "purge-deleted-metadata",
}

DELETE_RECORDINGS_WORKFLOW_TYPES = {
    "delete-recordings-with-person",
    "delete-recordings-with-team",
    "delete-recordings-with-query",
    "delete-recordings-with-session-ids",
    "purge-deleted-recording-metadata",
}

# ---------------------------------------------------------------------------
# Counter helpers (called from workflow code)
# ---------------------------------------------------------------------------


def increment_recordings_deleted(count: int) -> None:
    if count <= 0:
        return
    meter = get_metric_meter()
    meter.create_counter(
        "delete_recordings_total_deleted",
        "Total recordings successfully deleted",
    ).add(count)


def increment_recordings_failed(count: int) -> None:
    if count <= 0:
        return
    meter = get_metric_meter()
    meter.create_counter(
        "delete_recordings_total_failed",
        "Total recordings that failed to delete",
    ).add(count)


# ---------------------------------------------------------------------------
# Interceptor
# ---------------------------------------------------------------------------


class DeleteRecordingsMetricsInterceptor(Interceptor):
    task_queue = settings.SESSION_REPLAY_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _DeleteRecordingsActivityInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _DeleteRecordingsWorkflowInterceptor


class _DeleteRecordingsActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in DELETE_RECORDINGS_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            meter = get_metric_meter()
            meter.create_histogram_timedelta(
                name="delete_recordings_activity_schedule_to_start_latency",
                description="Time between activity scheduling and start",
                unit="ms",
            ).record(dt.timedelta(milliseconds=schedule_to_start_ms))

        with ExecutionTimeRecorder(
            "delete_recordings_activity_execution_latency",
            description="Execution latency for delete-recordings activities",
        ):
            return await super().execute_activity(input)


class _DeleteRecordingsWorkflowInterceptor(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput) -> typing.Any:
        workflow_info = workflow.info()
        workflow_type = workflow_info.workflow_type

        if workflow_type not in DELETE_RECORDINGS_WORKFLOW_TYPES:
            return await super().execute_workflow(input)

        meter = get_metric_meter()
        meter.create_counter(
            "delete_recordings_workflow_started",
            "Delete-recordings workflows started",
        ).add(1)

        with ExecutionTimeRecorder(
            "delete_recordings_workflow_execution_latency",
            description="End-to-end workflow execution latency",
        ):
            status = "COMPLETED"
            try:
                result = await super().execute_workflow(input)
                meter = get_metric_meter({"status": status})
                meter.create_counter(
                    "delete_recordings_workflow_finished",
                    "Delete-recordings workflows finished",
                ).add(1)
                return result
            except Exception:
                status = "FAILED"
                meter = get_metric_meter({"status": status})
                meter.create_counter(
                    "delete_recordings_workflow_finished",
                    "Delete-recordings workflows finished",
                ).add(1)
                raise
