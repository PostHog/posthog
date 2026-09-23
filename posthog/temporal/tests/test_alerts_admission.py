from datetime import UTC, datetime

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from posthog.redis import get_client
from posthog.temporal.alerts.admission import (
    INFLIGHT_KEY,
    SLOT_LEASE_SECONDS,
    admit_evaluation_slots,
    hold_evaluation_slot,
    inflight_alert_ids,
    release_evaluation_slot,
    release_evaluation_slots,
)

_AT_TEN = datetime(2026, 9, 22, 10, tzinfo=UTC).timestamp()  # where the frozen clocks below start


@pytest.fixture(autouse=True)
def clear_inflight_slots():
    get_client().delete(INFLIGHT_KEY)
    yield
    get_client().delete(INFLIGHT_KEY)


def _expiry(offset_seconds: float = 0) -> float:
    return _AT_TEN + offset_seconds + SLOT_LEASE_SECONDS


def test_admission_fills_only_the_free_capacity_and_slots_outlive_any_check() -> None:
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        first_hold = hold_evaluation_slot("running")
        assert admit_evaluation_slots(["a", "b", "c"], limit=3, expires_at=_expiry()) == ["a", "b"]
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(1)) == []
        assert inflight_alert_ids() == {"running", "a", "b"}

    # A check-alert workflow times out after 15 minutes, so every slot is still held one minute short of that.
    with time_machine.travel("2026-09-22T10:14:00Z", tick=False):
        second_hold = hold_evaluation_slot("running")
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(840)) == []
        release_evaluation_slots(["a"], held_until=_expiry())
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(840)) == ["c"]
        # The attempt that held first no longer owns the slot, so its release is a no-op.
        release_evaluation_slot("running", held_until=first_hold)
        assert "running" in inflight_alert_ids()

    # Past that, "b" lapses on its own; the slots held or admitted at 10:14 do not.
    with time_machine.travel("2026-09-22T10:16:00Z", tick=False):
        assert inflight_alert_ids() == {"running", "c"}
        release_evaluation_slot("running", held_until=second_hold)
        assert inflight_alert_ids() == {"c"}


def test_retried_admission_returns_its_first_result_and_another_run_gets_none_of_it() -> None:
    candidates = ["a", "b", "c", "d", "e", "f"]
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        first = admit_evaluation_slots(candidates, limit=4, expires_at=_expiry())
        retry = admit_evaluation_slots(candidates, limit=4, expires_at=_expiry())
        other_run = admit_evaluation_slots(candidates, limit=6, expires_at=_expiry(2))
        assert inflight_alert_ids() == set(candidates)
    assert first == ["a", "b", "c", "d"]
    assert retry == first
    assert other_run == ["e", "f"]


def test_scheduler_release_leaves_the_slot_a_running_check_holds() -> None:
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        held = hold_evaluation_slot("running")
        assert admit_evaluation_slots(["running", "fresh"], limit=3, expires_at=_expiry(1)) == ["fresh"]
        release_evaluation_slots(["running", "fresh"], held_until=_expiry(1))
        assert inflight_alert_ids() == {"running"}
        release_evaluation_slot("running", held_until=held)
        assert inflight_alert_ids() == set()


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
