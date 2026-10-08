import time
import threading
from typing import Any

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from posthog.dataclasses import frozen
from posthog.temporal.common.interceptor import ALL_TASK_QUEUES


@frozen
class RunningActivity:
    activity_type: str
    workflow_type: str | None
    workflow_id: str | None
    attempt: int
    started_at: float


class LivenessTracker:
    """Tracks the last time the worker successfully executed a workflow or activity.

    Used for k8s liveness/readiness probes to detect when a worker is alive
    but not processing work (e.g., due to GIL blocking, deadlocks, or event loop issues).
    """

    def __init__(self):
        self._last_activity_time: float = time.time()
        self._last_workflow_time: float = time.time()
        self._running_activities: dict[int, RunningActivity] = {}
        self._next_activity_key = 0
        self._lock = threading.Lock()

    def record_activity_start(self, activity: RunningActivity) -> int:
        """Register a running activity and return the key that `record_activity_end` takes."""

        with self._lock:
            key = self._next_activity_key
            self._next_activity_key += 1
            self._running_activities[key] = activity
            return key

    def record_activity_end(self, key: int) -> None:
        with self._lock:
            self._running_activities.pop(key, None)

    def get_running_activities(self) -> list[RunningActivity]:
        with self._lock:
            return list(self._running_activities.values())

    def record_activity_execution(self) -> None:
        """Record that an activity was executed."""

        with self._lock:
            self._last_activity_time = time.time()

    def record_workflow_execution(self) -> None:
        """Record that a workflow was executed."""

        with self._lock:
            self._last_workflow_time = time.time()

    def record_heartbeat(self) -> None:
        """Record an activity heartbeat.

        This is called during long-running activities to indicate the worker
        is still processing work, even if the activity hasn't completed yet.
        """

        with self._lock:
            self._last_activity_time = time.time()

    def get_last_execution_time(self) -> float:
        """Get the most recent execution time (activity or workflow)."""

        with self._lock:
            return max(self._last_activity_time, self._last_workflow_time)

    def is_healthy(self, max_idle_seconds: float) -> bool:
        """Check if the worker has executed something recently.

        Args:
            max_idle_seconds: Maximum time since last execution before considering unhealthy.

        Returns:
            True if the worker executed something within max_idle_seconds, False otherwise.
        """

        last_execution = self.get_last_execution_time()
        idle_time = time.time() - last_execution
        return idle_time < max_idle_seconds

    def get_idle_time(self) -> float:
        """Get the time since last execution in seconds."""

        return time.time() - self.get_last_execution_time()


# Global instance shared across the worker
_tracker = LivenessTracker()


def get_liveness_tracker() -> LivenessTracker:
    return _tracker


class _LivenessActivityInboundInterceptor(ActivityInboundInterceptor):
    _tracker: LivenessTracker

    def __init__(self, next: ActivityInboundInterceptor):
        super().__init__(next)
        self._tracker = get_liveness_tracker()

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        key = self._record_start() if activity.in_activity() else None
        try:
            result = await super().execute_activity(input)
            self._tracker.record_activity_execution()

            return result
        except Exception:
            self._tracker.record_activity_execution()
            raise
        finally:
            if key is not None:
                self._tracker.record_activity_end(key)

    def _record_start(self) -> int:
        info = activity.info()
        return self._tracker.record_activity_start(
            RunningActivity(
                activity_type=info.activity_type,
                workflow_type=info.workflow_type,
                workflow_id=info.workflow_id,
                attempt=info.attempt,
                started_at=time.time(),
            )
        )


class _LivenessWorkflowInterceptor(WorkflowInboundInterceptor):
    _tracker: LivenessTracker

    def __init__(self, next: WorkflowInboundInterceptor):
        super().__init__(next)
        self._tracker = get_liveness_tracker()

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        try:
            result = await super().execute_workflow(input)
            self._tracker.record_workflow_execution()

            return result
        except Exception:
            self._tracker.record_workflow_execution()
            raise


class LivenessInterceptor(Interceptor):
    """Interceptor that tracks worker liveness for health checks."""

    # Every queue, deliberately. This interceptor is what feeds the tracker behind `/healthz`, and
    # the health server is already opt-in per deployment (`TEMPORAL_HEALTH_PORT` +
    # `TEMPORAL_HEALTH_MAX_IDLE_SECONDS`). An allowlist here is a second, invisible opt-in that has
    # to be kept in sync with chart values in another repo, and when the two disagree the tracker is
    # never fed: `idle_seconds` silently becomes process uptime, so the liveness probe reaps every
    # replica at `max_idle_seconds` however busy it is. `start_temporal_worker` refuses to start a
    # health server on a queue this interceptor does not cover.
    task_queue = ALL_TASK_QUEUES

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _LivenessActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _LivenessWorkflowInterceptor
