from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.alerts_platform.backend.delivery import describers
from products.alerts_platform.backend.delivery.message import AlertMessage, build_message
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    MessageDetail,
    MessageLink,
    SourceDescription,
    SourceKind,
)


def _described_by(describer: Any) -> Any:
    return patch.dict(describers._describers, {SourceKind.LOGS: describer})


LOGS_DESCRIPTION = SourceDescription(
    details=(MessageDetail(label="Threshold breached", value="300 logs in 5m (threshold: above 100)"),),
    context=("Services: checkout",),
    data_link=MessageLink(label="View logs", url="https://app.example.com/project/7/logs"),
)

CONDITION = {"threshold_count": 100, "threshold_operator": "above", "window_minutes": 5}


def _transition(kind: AlertEventKind, **overrides: Any) -> AnnouncedTransition:
    fields: dict[str, Any] = {
        "grouping_key": "",
        "kind": kind,
        "episode_started_at": None,
        "value": 300.0,
        "labels": {},
        "condition": CONDITION,
        "source_config": {},
        "error_message": None,
        "occurred_at": datetime(2026, 9, 30, 10, tzinfo=UTC),
    }
    fields.update(overrides)
    return AnnouncedTransition(**fields)


def _announcement(consecutive_failures: int = 0, source: SourceKind = SourceKind.LOGS) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(
        configuration_id="cfg-1",
        source=source,
        alert_name="API errors",
        consecutive_failures=consecutive_failures,
        transitions=(),
    )


def _build(
    announcement: EvaluationAnnouncement,
    transition: AnnouncedTransition,
    *,
    incident_action: IncidentAction | None = None,
) -> AlertMessage:
    return build_message(announcement, transition, team_id=7, incident_action=incident_action)


class TestAlertMessage:
    @pytest.fixture(autouse=True)
    def _platform_wording_only(self) -> Iterator[None]:
        # Sources register describers at startup. These tests state the platform's own wording, and
        # the describer tests register theirs on top of this.
        with patch.dict(describers._describers, {}, clear=True):
            yield

    @pytest.mark.parametrize(
        "source,expected_headline",
        [
            (SourceKind.LOGS, "Log alert 'API errors' is firing"),
            (SourceKind.INSIGHT, "Insight alert 'API errors' is firing"),
        ],
    )
    def test_a_message_names_its_source_and_links_to_its_alert(
        self, source: SourceKind, expected_headline: str
    ) -> None:
        message = _build(_announcement(source=source), _transition(AlertEventKind.FIRING))

        assert message.headline == expected_headline
        assert message.alert_url.endswith("/project/7/platform-alerts/cfg-1")

    @pytest.mark.parametrize("source", list(SourceKind))
    def test_every_source_kind_has_a_headline(self, source: SourceKind) -> None:
        message = _build(_announcement(source=source), _transition(AlertEventKind.FIRING))

        assert message.headline.endswith("alert 'API errors' is firing")

    def test_a_breach_states_what_it_measured_against_what_it_allowed(self) -> None:
        message = _build(_announcement(), _transition(AlertEventKind.FIRING))

        assert message.details == (
            MessageDetail(label="Value", value="300"),
            MessageDetail(label="Threshold", value="above 100"),
            MessageDetail(label="Window", value="5 minutes"),
        )

    def test_a_failed_check_states_the_reason_rather_than_a_threshold(self) -> None:
        message = _build(
            _announcement(consecutive_failures=3),
            _transition(AlertEventKind.ERRORED, value=None, error_message="Query is too expensive"),
        )

        assert message.headline == "Log alert 'API errors' could not be checked"
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
        message = _build(_announcement(), _transition(AlertEventKind.FIRING, condition=condition))

        assert MessageDetail(label="Window", value=expected) in message.details

    def test_a_check_that_announces_nothing_has_no_message(self) -> None:
        with pytest.raises(ValueError):
            _build(_announcement(), _transition(AlertEventKind.CHECK))

    @pytest.mark.parametrize(
        "action,expected,symbol",
        [
            (IncidentAction.TRIGGER, "Log alert 'API errors' is firing", "\U0001f534"),
            (IncidentAction.RESOLVE, "Log alert 'API errors' is resolved", "\U0001f7e2"),
        ],
    )
    def test_a_held_check_speaks_for_the_incident_it_moved(
        self, action: IncidentAction, expected: str, symbol: str
    ) -> None:
        message = _build(_announcement(), _transition(AlertEventKind.CHECK), incident_action=action)

        assert (message.headline, message.symbol, message.incident_action) == (expected, symbol, action)

    def test_a_source_words_a_breach_in_its_own_vocabulary(self) -> None:
        with _described_by(lambda **_: LOGS_DESCRIPTION):
            message = _build(_announcement(), _transition(AlertEventKind.FIRING))

        assert (message.details, message.context, message.data_link) == (
            LOGS_DESCRIPTION.details,
            LOGS_DESCRIPTION.context,
            LOGS_DESCRIPTION.data_link,
        )

    def test_a_failed_check_keeps_the_platform_failure_details_under_a_source_description(self) -> None:
        with _described_by(lambda **_: LOGS_DESCRIPTION):
            message = _build(
                _announcement(consecutive_failures=3),
                _transition(AlertEventKind.ERRORED, value=None, error_message="Query is too expensive"),
            )

        assert message.details[0] == MessageDetail(label="Error", value="Query is too expensive")
        assert message.data_link == LOGS_DESCRIPTION.data_link

    def test_a_source_link_too_long_for_slack_is_left_out(self) -> None:
        long_link = MessageLink(label="View logs", url="https://app.example.com/logs?" + "q" * 3000)
        description = SourceDescription(context=("Services: checkout",), data_link=long_link)

        with _described_by(lambda **_: description):
            message = _build(_announcement(), _transition(AlertEventKind.FIRING))

        assert (message.context, message.data_link) == (("Services: checkout",), None)

    @pytest.mark.parametrize("answer", ["raises", "returns_none"])
    def test_a_broken_describer_still_delivers_the_platform_wording(self, answer: str) -> None:
        def broken(**_: Any) -> Any:
            if answer == "raises":
                raise KeyError("serviceNames")
            return None

        with _described_by(broken):
            message = _build(_announcement(), _transition(AlertEventKind.FIRING))

        assert MessageDetail(label="Threshold", value="above 100") in message.details
        assert (message.context, message.data_link) == ((), None)

    def test_a_partial_condition_drops_the_line_it_cannot_state(self) -> None:
        message = _build(_announcement(), _transition(AlertEventKind.FIRING, condition={}))

        assert message.details == (MessageDetail(label="Value", value="300"),)
