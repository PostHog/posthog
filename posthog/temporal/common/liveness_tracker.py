import time
import datetime as dt
import threading
import contextvars
import dataclasses
from collections.abc import Callable
from typing import Any

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ActivityOutboundInterceptor,
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
    is_local: bool = False
    # Server clock, as Unix seconds. The server measures `start_to_close_timeout` from
    # `server_started_at` and `schedule_to_close_timeout` from `scheduled_at`.
    server_started_at: float | None = None
    scheduled_at: float | None = None
    start_to_close_timeout: float | None = None
    schedule_to_close_timeout: float | None = None
    heartbeat_timeout: float | None = None
    last_heartbeat_at: float | None = None
    # The longest time this attempt went without a heartbeat. It stays set when heartbeats start
    # again, because the server does not reopen an attempt that it timed out.
    max_heartbeat_gap: float = 0.0
    cancellation_details: Callable[[], activity.ActivityCancellationDetails | None] | None = None


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
        self._last_activity_end_time: float | None = None
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
            self._last_activity_end_time = time.time()

    def record_activity_heartbeat(self, key: int) -> None:
        now = time.time()
        with self._lock:
            running = self._running_activities.get(key)
            if running is None:
                return
            gap = now - (running.last_heartbeat_at or running.started_at)
            self._running_activities[key] = dataclasses.replace(
                running,
                last_heartbeat_at=now,
                max_heartbeat_gap=max(running.max_heartbeat_gap, gap),
            )

    def get_last_activity_end_time(self) -> float | None:
        """Return when an activity last handed its result to the SDK, or `None` if none did."""

        with self._lock:
            return self._last_activity_end_time

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


def _total_seconds(timeout: dt.timedelta | None) -> float | None:
    return timeout.total_seconds() if timeout is not None else None


class _LivenessActivityOutboundInterceptor(ActivityOutboundInterceptor):
    def __init__(self, next: ActivityOutboundInterceptor, on_heartbeat: Callable[[], None]):
        super().__init__(next)
        self._on_heartbeat = on_heartbeat

    def heartbeat(self, *details: Any) -> None:
        super().heartbeat(*details)
        self._on_heartbeat()


class _LivenessActivityInboundInterceptor(ActivityInboundInterceptor):
    _tracker: LivenessTracker

    def __init__(self, next: ActivityInboundInterceptor):
        super().__init__(next)
        self._tracker = get_liveness_tracker()
        self._key: int | None = None

    def init(self, outbound: ActivityOutboundInterceptor) -> None:
        super().init(_LivenessActivityOutboundInterceptor(outbound, self._record_heartbeat))

    def _record_heartbeat(self) -> None:
        if self._key is not None:
            self._tracker.record_activity_heartbeat(self._key)

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        key = self._key = self._record_start() if activity.in_activity() else None
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
        # The shutdown path reads the cancellation details from a thread that has no activity
        # context, so it needs a copy of this context to run `activity.cancellation_details` in.
        context = contextvars.copy_context()
        return self._tracker.record_activity_start(
            RunningActivity(
                activity_type=info.activity_type,
                workflow_type=info.workflow_type,
                workflow_id=info.workflow_id,
                attempt=info.attempt,
                started_at=time.time(),
                is_local=info.is_local,
                server_started_at=info.started_time.timestamp(),
                scheduled_at=info.scheduled_time.timestamp(),
                start_to_close_timeout=_total_seconds(info.start_to_close_timeout),
                schedule_to_close_timeout=_total_seconds(info.schedule_to_close_timeout),
                heartbeat_timeout=_total_seconds(info.heartbeat_timeout),
                cancellation_details=lambda: context.run(activity.cancellation_details),
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
