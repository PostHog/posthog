import time
import threading
from typing import Any

from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


class LivenessTracker:
    """Tracks the last time the worker successfully executed a workflow or activity.

    Used for k8s liveness/readiness probes to detect when a worker is alive
    but not processing work (e.g., due to GIL blocking, deadlocks, or event loop issues).
    """

    def __init__(self):
        self._last_activity_time: float = time.time()
        self._last_workflow_time: float = time.time()
        self._lock = threading.Lock()

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
        try:
            result = await super().execute_activity(input)
            self._tracker.record_activity_execution()

            return result
        except Exception:
            self._tracker.record_activity_execution()
            raise


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

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _LivenessActivityInboundInterceptor(super().intercept_activity(next))

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _LivenessWorkflowInterceptor
