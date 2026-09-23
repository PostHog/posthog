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
        assert admit_evaluation_slots(["a", "b", "c"], limit=3) == ["a", "b"]
        assert admit_evaluation_slots(["c"], limit=3) == []
        assert inflight_alert_ids() == {"running", "a", "b"}

    # A check-alert workflow times out after 15 minutes, so every slot is still held one minute short of that.
    with time_machine.travel("2026-09-22T10:14:00Z", tick=False):
        second_hold = hold_evaluation_slot("running")
        assert admit_evaluation_slots(["c"], limit=3) == []
        release_evaluation_slots(["a"])
        assert admit_evaluation_slots(["c"], limit=3) == ["c"]
        # The attempt that held first no longer owns the slot, so its release is a no-op.
        release_evaluation_slot("running", held_until=first_hold)
        assert "running" in inflight_alert_ids()

    # Past that, "b" lapses on its own; the slots held or admitted at 10:14 do not.
    with time_machine.travel("2026-09-22T10:16:00Z", tick=False):
        assert inflight_alert_ids() == {"running", "c"}
        release_evaluation_slot("running", held_until=second_hold)
        assert count_inflight_evaluations() == 1


def test_hold_raises_when_redis_stays_unavailable() -> None:
    client = MagicMock()
    client.eval.side_effect = ConnectionError("redis down")
    with (
        patch("posthog.temporal.alerts.admission.redis.get_client", return_value=client),
        patch("posthog.temporal.alerts.admission.time.sleep"),
        pytest.raises(ConnectionError),
    ):
        hold_evaluation_slot("x")
    assert client.eval.call_count == 3
