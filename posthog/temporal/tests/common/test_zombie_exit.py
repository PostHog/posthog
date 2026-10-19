import pytest

from temporalio.activity import ActivityCancellationDetails

from posthog.temporal.common.liveness_tracker import LivenessTracker, RunningActivity
from posthog.temporal.common.zombie_exit import (
    DEADLINE_MARGIN_SECONDS,
    RESULT_FLUSH_SECONDS,
    ZombieActivityExit,
    classify_zombie,
)

NOW = 1_000_000.0
GRACE = 180.0


def _activity(activity_type: str = "sync_new_schemas_activity", age: float = 3600.0, **overrides) -> RunningActivity:
    fields: dict = {
        "activity_type": activity_type,
        "workflow_type": "some-workflow",
        "workflow_id": "wf-1",
        "attempt": 1,
        "started_at": NOW - age,
        "server_started_at": NOW - age,
        "scheduled_at": NOW - age,
    }
    return RunningActivity(**(fields | overrides))


def _past_start_to_close(**overrides) -> RunningActivity:
    return _activity(start_to_close_timeout=600.0, **overrides)


def _live(**overrides) -> RunningActivity:
    fields: dict = {
        "activity_type": "import_data_activity_sync",
        "start_to_close_timeout": 86_400.0,
        "heartbeat_timeout": 120.0,
        "last_heartbeat_at": NOW - 4.0,
        "max_heartbeat_gap": 5.0,
    }
    return _activity(**(fields | overrides))


@pytest.mark.parametrize(
    "running,expected_reason",
    [
        (_past_start_to_close(), "start_to_close_timeout"),
        (_activity(start_to_close_timeout=3600.0 - DEADLINE_MARGIN_SECONDS + 1), None),
        (
            _activity(age=600.0, start_to_close_timeout=3600.0, schedule_to_close_timeout=300.0),
            "schedule_to_close_timeout",
        ),
        (_activity(start_to_close_timeout=86_400.0, heartbeat_timeout=120.0), "heartbeat_timeout"),
        (
            _activity(start_to_close_timeout=86_400.0, heartbeat_timeout=120.0, last_heartbeat_at=NOW - 500.0),
            "heartbeat_timeout",
        ),
        (
            _activity(
                start_to_close_timeout=86_400.0,
                heartbeat_timeout=120.0,
                last_heartbeat_at=NOW - 120.0 - DEADLINE_MARGIN_SECONDS + 1,
            ),
            None,
        ),
        # Heartbeats that start again do not reopen an attempt the server timed out.
        (
            _activity(
                start_to_close_timeout=86_400.0,
                heartbeat_timeout=120.0,
                last_heartbeat_at=NOW - 1.0,
                max_heartbeat_gap=900.0,
            ),
            "heartbeat_timeout",
        ),
        (_live(), None),
        (_activity(), None),
        (_past_start_to_close(is_local=True), None),
        (_live(cancellation_details=lambda: ActivityCancellationDetails(not_found=True)), "not_found"),
        (_live(cancellation_details=lambda: ActivityCancellationDetails(timed_out=True)), "timed_out"),
        (_live(cancellation_details=lambda: ActivityCancellationDetails(cancel_requested=True)), None),
        (_live(cancellation_details=lambda: ActivityCancellationDetails(worker_shutdown=True)), None),
        (_live(cancellation_details=lambda: None), None),
    ],
)
def test_classify_zombie(running: RunningActivity, expected_reason: str | None) -> None:
    zombie = classify_zombie(running, NOW)

    assert (zombie.reason if zombie else None) == expected_reason


class _FakeTime:
    def __init__(self, max_waits: int = 50) -> None:
        self.now = NOW
        self.max_waits = max_waits
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now += seconds
        return len(self.waits) >= self.max_waits


def _run(tracker: LivenessTracker, fake_time: _FakeTime) -> list[int]:
    exit_codes: list[int] = []
    ZombieActivityExit(
        tracker=tracker,
        grace_seconds=GRACE,
        task_queue="test-task-queue",
        exit_process=exit_codes.append,
        clock=fake_time.clock,
        wait=fake_time.wait,
    ).run()
    return exit_codes


@pytest.mark.parametrize(
    "running,expected_exit_codes",
    [
        ([_past_start_to_close()], [0]),
        ([_past_start_to_close(), _activity(start_to_close_timeout=86_400.0, heartbeat_timeout=120.0)], [0]),
        ([_live(start_to_close_timeout=10 * 86_400.0, heartbeat_timeout=None)], []),
        ([_past_start_to_close(), _live(start_to_close_timeout=10 * 86_400.0, heartbeat_timeout=None)], []),
        ([], []),
    ],
    ids=["zombie_only", "zombies_of_two_kinds", "live_only", "zombie_and_live", "nothing_running"],
)
def test_exits_only_when_every_running_activity_is_a_zombie(
    running: list[RunningActivity], expected_exit_codes: list[int]
) -> None:
    tracker = LivenessTracker()
    for activity in running:
        tracker.record_activity_start(activity)
    fake_time = _FakeTime()

    assert _run(tracker, fake_time) == expected_exit_codes
    assert fake_time.waits[0] == GRACE


def test_exits_once_the_last_live_activity_returns_and_its_result_had_time_to_flush() -> None:
    tracker = LivenessTracker()
    tracker.record_activity_start(_past_start_to_close())
    live_key = tracker.record_activity_start(_live(start_to_close_timeout=10 * 86_400.0, heartbeat_timeout=None))
    fake_time = _FakeTime()
    exit_times: list[float] = []
    live_ended_at: list[float] = []

    def wait(seconds: float) -> bool:
        stop = fake_time.wait(seconds)
        if len(fake_time.waits) == 4:
            tracker.record_activity_end(live_key)
            tracker._last_activity_end_time = fake_time.now
            live_ended_at.append(fake_time.now)
        return stop

    ZombieActivityExit(
        tracker=tracker,
        grace_seconds=GRACE,
        task_queue="test-task-queue",
        exit_process=lambda _code: exit_times.append(fake_time.now),
        clock=fake_time.clock,
        wait=wait,
    ).run()

    assert len(exit_times) == 1
    assert exit_times[0] - live_ended_at[0] >= RESULT_FLUSH_SECONDS


def test_does_not_exit_when_the_worker_stops_during_the_grace() -> None:
    tracker = LivenessTracker()
    tracker.record_activity_start(_past_start_to_close())

    assert _run(tracker, _FakeTime(max_waits=1)) == []
