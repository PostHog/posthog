import pytest
import time_machine
from unittest.mock import MagicMock, patch

from posthog.redis import get_client
from posthog.temporal.alerts.admission import (
    INFLIGHT_KEY,
    admit_evaluation_slots,
    count_inflight_evaluations,
    hold_evaluation_slot,
    inflight_alert_ids,
    release_evaluation_slot,
    release_evaluation_slots,
)


@pytest.fixture(autouse=True)
def clear_inflight_slots():
    get_client().delete(INFLIGHT_KEY)
    yield
    get_client().delete(INFLIGHT_KEY)


def test_admission_fills_only_the_free_capacity_and_slots_outlive_any_check() -> None:
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        first_hold = hold_evaluation_slot("running")
        first_admission = admit_evaluation_slots(["a", "b", "c"], limit=3)
        assert first_admission.alert_ids == ["a", "b"]
        assert first_admission.occupied == 3
        assert admit_evaluation_slots(["c"], limit=3).alert_ids == []
        assert inflight_alert_ids() == {"running", "a", "b"}

    # A check-alert workflow times out after 15 minutes, so every slot is still held one minute short of that.
    with time_machine.travel("2026-09-22T10:14:00Z", tick=False):
        second_hold = hold_evaluation_slot("running")
        assert admit_evaluation_slots(["c"], limit=3).alert_ids == []
        release_evaluation_slots(["a"], held_until=first_admission.expires_at)
        assert admit_evaluation_slots(["c"], limit=3).alert_ids == ["c"]
        # The attempt that held first no longer owns the slot, so its release is a no-op.
        release_evaluation_slot("running", held_until=first_hold)
        assert "running" in inflight_alert_ids()

    # Past that, "b" lapses on its own; the slots held or admitted at 10:14 do not.
    with time_machine.travel("2026-09-22T10:16:00Z", tick=False):
        assert inflight_alert_ids() == {"running", "c"}
        release_evaluation_slot("running", held_until=second_hold)
        assert count_inflight_evaluations() == 1


def test_retried_admission_returns_its_first_result_without_taking_more_slots() -> None:
    candidates = ["a", "b", "c", "d", "e", "f"]
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        first = admit_evaluation_slots(candidates, limit=4)
    with time_machine.travel("2026-09-22T10:00:01Z", tick=False):
        retry = admit_evaluation_slots(candidates, limit=4)
    assert first.alert_ids == ["a", "b", "c", "d"]
    assert retry.alert_ids == first.alert_ids
    assert retry.occupied == 4


def test_scheduler_release_leaves_the_slot_a_running_check_holds() -> None:
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        held = hold_evaluation_slot("running")
    with time_machine.travel("2026-09-22T10:00:01Z", tick=False):
        admission = admit_evaluation_slots(["running", "fresh"], limit=3)
        assert admission.alert_ids == ["running", "fresh"]
        release_evaluation_slots(admission.alert_ids, held_until=admission.expires_at)
        assert inflight_alert_ids() == {"running"}
        release_evaluation_slot("running", held_until=held)
        assert count_inflight_evaluations() == 0


def test_hold_raises_when_redis_stays_unavailable() -> None:
    client = MagicMock()
    client.zadd.side_effect = ConnectionError("redis down")
    with (
        patch("posthog.temporal.alerts.admission.redis.get_client", return_value=client),
        patch("posthog.temporal.alerts.admission.time.sleep"),
        pytest.raises(ConnectionError),
    ):
        hold_evaluation_slot("x")
    assert client.zadd.call_count == 3
