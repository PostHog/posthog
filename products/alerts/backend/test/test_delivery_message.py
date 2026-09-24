from typing import Any

import pytest

from products.alerts.backend.delivery.message import MessageDetail, build_message
from products.alerts.backend.facade.contracts import AlertEventKind, EvaluationAnnouncement, GroupTransition

CONDITION = {"threshold_count": 100, "threshold_operator": "above", "window_minutes": 5}


def _transition(kind: AlertEventKind, **overrides: Any) -> GroupTransition:
    fields: dict[str, Any] = {
        "grouping_key": "",
        "kind": kind,
        "previous_state": "not_firing",
        "state": "firing",
        "value": 300.0,
        "labels": {},
        "condition": CONDITION,
        "source_config": {},
        "error_message": None,
    }
    fields.update(overrides)
    return GroupTransition(**fields)


def _announcement(consecutive_failures: int = 0) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(alert_name="API errors", consecutive_failures=consecutive_failures, notifications=())


class TestAlertMessage:
    def test_a_breach_states_what_it_measured_against_what_it_allowed(self) -> None:
        message = build_message(_announcement(), _transition(AlertEventKind.FIRING))

        assert message.headline == "API errors is firing"
        assert message.details == (
            MessageDetail(label="Value", value="300"),
            MessageDetail(label="Threshold", value="above 100"),
            MessageDetail(label="Window", value="5 minutes"),
        )

    def test_a_failed_check_states_the_reason_rather_than_a_threshold(self) -> None:
        message = build_message(
            _announcement(consecutive_failures=3),
            _transition(AlertEventKind.ERRORED, value=None, error_message="Query is too expensive"),
        )

        assert message.headline == "API errors could not be checked"
        assert message.details == (
            MessageDetail(label="Error", value="Query is too expensive"),
            MessageDetail(label="Failed checks", value="3"),
        )

    @pytest.mark.parametrize(
        "window_minutes,expected",
        [(1, "1 minute"), (5, "5 minutes")],
    )
    def test_the_window_reads_as_a_duration(self, window_minutes: int, expected: str) -> None:
        condition = {**CONDITION, "window_minutes": window_minutes}
        message = build_message(_announcement(), _transition(AlertEventKind.FIRING, condition=condition))

        assert MessageDetail(label="Window", value=expected) in message.details

    def test_a_check_that_announces_nothing_has_no_message(self) -> None:
        with pytest.raises(ValueError):
            build_message(_announcement(), _transition(AlertEventKind.CHECK))

    def test_a_partial_condition_drops_the_line_it_cannot_state(self) -> None:
        message = build_message(_announcement(), _transition(AlertEventKind.FIRING, condition={}))

        assert message.details == (MessageDetail(label="Value", value="300"),)
