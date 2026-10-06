from datetime import UTC, datetime

import pytest
import time_machine

from posthog.redis import get_client
from posthog.temporal.alerts.admission import (
    INFLIGHT_KEY,
    SLOT_LEASE_SECONDS,
    admit_evaluation_slots,
    hold_evaluation_slot,
    inflight_alert_ids,
    refresh_evaluation_slot,
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


def _at(offset_seconds: float) -> datetime:
    return datetime.fromtimestamp(_AT_TEN + offset_seconds, tz=UTC)


def _hold(alert_id: str, *, limit: int, lease_seconds: float = SLOT_LEASE_SECONDS) -> float:
    held = hold_evaluation_slot(alert_id, limit=limit, lease_seconds=lease_seconds)
    assert held is not None
    return held


def test_admission_fills_only_the_free_capacity_and_slots_outlive_any_check() -> None:
    with time_machine.travel(_at(0), tick=False):
        first_hold = _hold("running", limit=3)
        assert admit_evaluation_slots(["a", "b", "c"], limit=3, expires_at=_expiry()) == ["a", "b"]
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(1)) == []
        # A check that lost its slot to a full set gets none back; one still in the set re-holds regardless.
        assert hold_evaluation_slot("c", limit=3) is None
        assert hold_evaluation_slot("a", limit=3) == _expiry()
        assert inflight_alert_ids() == {"running", "a", "b"}

    # The scheduler's lease is the workflow timeout, so every slot is still held one minute short of it.
    one_minute_short = SLOT_LEASE_SECONDS - 60
    with time_machine.travel(_at(one_minute_short), tick=False):
        second_hold = _hold("running", limit=3)
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(one_minute_short)) == []
        release_evaluation_slots(["a"], held_until=_expiry())
        assert admit_evaluation_slots(["c"], limit=3, expires_at=_expiry(one_minute_short)) == ["c"]
        # The attempt that held first no longer owns the slot, so its release is a no-op.
        release_evaluation_slot("running", held_until=first_hold)
        assert "running" in inflight_alert_ids()

    # Past that, "b" lapses on its own; the slots held or admitted one minute short do not.
    with time_machine.travel(_at(SLOT_LEASE_SECONDS + 60), tick=False):
        assert inflight_alert_ids() == {"running", "c"}
        release_evaluation_slot("running", held_until=second_hold)
        assert inflight_alert_ids() == {"c"}


def test_refresh_moves_only_the_expiry_its_holder_wrote() -> None:
    with time_machine.travel(_at(0), tick=False):
        held = _hold("running", limit=1, lease_seconds=120)
        assert refresh_evaluation_slot("running", held_until=held, expires_at=_AT_TEN + 300) is True
        # The expiry the holder first wrote no longer identifies it, and an unheld member is not created.
        assert refresh_evaluation_slot("running", held_until=held, expires_at=_AT_TEN + 900) is False
        assert refresh_evaluation_slot("absent", held_until=held, expires_at=_AT_TEN + 900) is False
    with time_machine.travel(_at(240), tick=False):
        assert inflight_alert_ids() == {"running"}
    with time_machine.travel(_at(360), tick=False):
        assert inflight_alert_ids() == set()


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
        held = _hold("running", limit=3)
        assert admit_evaluation_slots(["running", "fresh"], limit=3, expires_at=_expiry(1)) == ["fresh"]
        release_evaluation_slots(["running", "fresh"], held_until=_expiry(1))
        assert inflight_alert_ids() == {"running"}
        release_evaluation_slot("running", held_until=held)
        assert inflight_alert_ids() == set()
