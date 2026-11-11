import os
import sys
import time
import threading
from collections.abc import Callable

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.temporal.common.liveness_tracker import LivenessTracker, RunningActivity
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)

# Added to each server deadline before the worker treats it as passed. It covers the clock
# difference between the worker and the server, the delay of the server timeout timer, and the
# time the SDK holds a heartbeat back before it sends it (`max_heartbeat_throttle_interval`).
DEADLINE_MARGIN_SECONDS = 60.0

# An activity that returned still has its result on the way to the server. The worker does not
# exit until this long after the last activity returned, so that result is not lost.
RESULT_FLUSH_SECONDS = 30.0

POLL_INTERVAL_SECONDS = 5.0

# Prometheus pulls the counter, so the process stays up for a short time to give a scrape a
# chance. The log lines are the complete record if no scrape comes in time.
METRICS_SCRAPE_WAIT_SECONDS = 15.0

ABANDONED_ACTIVITIES_COUNTER = Counter(
    "temporal_worker_shutdown_abandoned_activities_total",
    "Activities a worker abandoned at shutdown because the Temporal server had already closed them.",
    labelnames=["task_queue", "activity_type", "reason"],
)


@frozen
class ZombieActivity:
    activity: RunningActivity
    reason: str
    timeout_seconds: float | None
    seconds_past_deadline: float | None


def classify_zombie(
    running: RunningActivity, now: float, margin: float = DEADLINE_MARGIN_SECONDS
) -> ZombieActivity | None:
    """Return why the server no longer accepts a result from this activity, or `None` if it can."""

    # The server does not track a local activity, so the worker has no deadline to compare.
    if running.is_local:
        return None

    details = running.cancellation_details() if running.cancellation_details is not None else None
    if details is not None and (details.not_found or details.timed_out):
        return ZombieActivity(
            activity=running,
            reason="timed_out" if details.timed_out else "not_found",
            timeout_seconds=None,
            seconds_past_deadline=None,
        )

    if running.start_to_close_timeout is not None and running.server_started_at is not None:
        past = now - (running.server_started_at + running.start_to_close_timeout)
        if past > margin:
            return ZombieActivity(
                activity=running,
                reason="start_to_close_timeout",
                timeout_seconds=running.start_to_close_timeout,
                seconds_past_deadline=past,
            )

    if running.schedule_to_close_timeout is not None and running.scheduled_at is not None:
        past = now - (running.scheduled_at + running.schedule_to_close_timeout)
        if past > margin:
            return ZombieActivity(
                activity=running,
                reason="schedule_to_close_timeout",
                timeout_seconds=running.schedule_to_close_timeout,
                seconds_past_deadline=past,
            )

    if running.heartbeat_timeout is not None:
        current_gap = now - (running.last_heartbeat_at or running.started_at)
        past = max(current_gap, running.max_heartbeat_gap) - running.heartbeat_timeout
        if past > margin:
            return ZombieActivity(
                activity=running,
                reason="heartbeat_timeout",
                timeout_seconds=running.heartbeat_timeout,
                seconds_past_deadline=past,
            )

    return None


class ZombieActivityExit:
    """Exits a worker that is shutting down when only zombie activities hold it.

    A zombie activity is one the Temporal server already closed: it timed the attempt out, and it
    retries the attempt on another worker if attempts remain. The thread of such an activity can
    stay blocked in a call that never returns, and `Worker.shutdown()` waits for it until the
    graceful shutdown timeout ends. That thread can no longer report a result, so the wait has no
    use.

    The check runs on its own thread, so it also works when the event loop is blocked.
    """

    def __init__(
        self,
        tracker: LivenessTracker,
        grace_seconds: float,
        task_queue: str,
        exit_process: Callable[[int], None] = os._exit,
        clock: Callable[[], float] = time.time,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._tracker = tracker
        self._grace_seconds = grace_seconds
        self._task_queue = task_queue
        self._exit_process = exit_process
        self._clock = clock
        self._stopped = threading.Event()
        self._wait = wait if wait is not None else self._stopped.wait
        self._logger = LOGGER.bind(task_queue=task_queue)

    def start(self) -> None:
        thread = threading.Thread(target=self.run, name="zombie-activity-exit", daemon=True)
        thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def find_zombies_if_only_zombies_remain(self) -> list[ZombieActivity] | None:
        """Return the zombie activities when the worker can exit now, else `None`."""

        now = self._clock()
        running = self._tracker.get_running_activities()
        # With no activity left, `Worker.shutdown()` returns without help.
        if not running:
            return None

        last_end = self._tracker.get_last_activity_end_time()
        if last_end is not None and now - last_end < RESULT_FLUSH_SECONDS:
            return None

        zombies: list[ZombieActivity] = []
        for activity in running:
            zombie = classify_zombie(activity, now)
            if zombie is None:
                return None
            zombies.append(zombie)
        return zombies

    def run(self) -> None:
        if self._wait(self._grace_seconds):
            return

        while True:
            zombies = self.find_zombies_if_only_zombies_remain()
            if zombies is not None:
                self._abandon(zombies)
                return
            if self._wait(POLL_INTERVAL_SECONDS):
                return

    def _abandon(self, zombies: list[ZombieActivity]) -> None:
        now = self._clock()
        self._logger.warning("Exiting worker because only zombie activities remain", count=len(zombies))
        for zombie in zombies:
            running = zombie.activity
            self._logger.warning(
                "Zombie activity abandoned at shutdown",
                activity_type=running.activity_type,
                workflow_type=running.workflow_type,
                workflow_id=running.workflow_id,
                attempt=running.attempt,
                running_seconds=round(now - running.started_at),
                reason=zombie.reason,
                timeout_seconds=zombie.timeout_seconds,
                seconds_past_deadline=(
                    round(zombie.seconds_past_deadline) if zombie.seconds_past_deadline is not None else None
                ),
            )
            ABANDONED_ACTIVITIES_COUNTER.labels(
                task_queue=self._task_queue, activity_type=running.activity_type, reason=zombie.reason
            ).inc()

        if self._wait(METRICS_SCRAPE_WAIT_SECONDS):
            return
        sys.stdout.flush()
        sys.stderr.flush()
        self._exit_process(0)
