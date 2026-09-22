import pytest
import time_machine

from posthog.redis import get_client
from posthog.temporal.alerts.admission import (
    INFLIGHT_KEY,
    admit_evaluation_slots,
    count_inflight_evaluations,
    hold_evaluation_slot,
    inflight_alert_ids,
    release_evaluation_slot,
)


@pytest.fixture(autouse=True)
def clear_inflight_slots():
    get_client().delete(INFLIGHT_KEY)
    yield
    get_client().delete(INFLIGHT_KEY)


def test_admission_fills_only_the_free_capacity_and_slots_outlive_any_check() -> None:
    with time_machine.travel("2026-09-22T10:00:00Z", tick=False):
        hold_evaluation_slot("running")
        assert admit_evaluation_slots(["a", "b", "c"], limit=3) == ["a", "b"]
        assert admit_evaluation_slots(["c"], limit=3) == []
        assert inflight_alert_ids() == {"running", "a", "b"}

    # A check-alert workflow times out after 15 minutes, so every slot is still held one minute short of that.
    with time_machine.travel("2026-09-22T10:14:00Z", tick=False):
        hold_evaluation_slot("running")
        assert admit_evaluation_slots(["c"], limit=3) == []
        release_evaluation_slot("a")
        assert admit_evaluation_slots(["c"], limit=3) == ["c"]

    # Past that, "b" lapses on its own; the slots held or admitted at 10:14 do not.
    with time_machine.travel("2026-09-22T10:16:00Z", tick=False):
        assert inflight_alert_ids() == {"running", "c"}
        assert count_inflight_evaluations() == 2
