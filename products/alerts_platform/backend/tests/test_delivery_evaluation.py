from datetime import UTC, datetime
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups
from products.alerts_platform.backend.delivery.evaluation import LIVE_DELIVERY_FLAG, deliver_evaluation
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertDestinationGroup,
    AlertEventKind,
    AnnouncedTransition,
    DestinationType,
    EvaluationAnnouncement,
    SourceKind,
)

_MODULE = "products.alerts_platform.backend.delivery.evaluation"
FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)

FIRING_EVENT = "$logs_alert_firing"
RESOLVED_EVENT = "$logs_alert_resolved"

SLACK = cast(AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-1"})
WEBHOOK = cast(AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"})
TEAMS = cast(AlertDestinationData, {"type": DestinationType.TEAMS, "webhook_url": "https://example.com/teams"})
UNSUPPORTED = cast(AlertDestinationData, {"type": "pagerduty"})


class RecordingTransport:
    """Stands in for Slack at the edge, so everything inside `deliver` stays real."""

    sends: list[tuple[str, AlertMessage]] = []
    provider = "slack"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("slack_channel_id", ""))

    def deliver(
        self, *, team_id: int, target: AlertDestinationData, message: AlertMessage, in_reply_to: Any = None
    ) -> MessageHandle | None:
        RecordingTransport.sends.append((self.channel_target(target), message))
        return MessageHandle(external_ref={"channel": self.channel_target(target), "ts": "1"})


class RefusingTransport(RecordingTransport):
    provider = "webhook"

    def deliver(self, **kwargs: Any) -> MessageHandle | None:
        raise DeliveryError("The webhook destination refused the message with status 410.")


class HeldTransport(RecordingTransport):
    provider = "teams"

    def deliver(self, **kwargs: Any) -> MessageHandle | None:
        raise ThreadBusy("thread is being posted to by another send")


def _request(team_id: int) -> AlertDeliveryRequest:
    return AlertDeliveryRequest(
        source=SourceKind.LOGS,
        team_id=team_id,
        configuration_id="cfg-1",
        evaluation_key="eval-1",
        destination_alert_id="legacy-1",
        event_ids_by_kind={"firing": FIRING_EVENT, "resolved": RESOLVED_EVENT},
    )


def _transition(kind: AlertEventKind, grouping_key: str = "") -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key=grouping_key,
        kind=kind,
        episode_started_at=FIRING,
        value=None,
        labels={},
        condition={},
        source_config={},
        error_message=None,
        occurred_at=FIRING,
    )


def _announcement(*transitions: AnnouncedTransition) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(
        configuration_id="cfg-1", alert_name="API errors", consecutive_failures=0, transitions=transitions
    )


def _group(data: AlertDestinationData, fully_enabled: bool = True) -> AlertDestinationGroup:
    return AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=fully_enabled)


class TestDeliverEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []

    def _run(
        self,
        announced: Any,
        by_event: dict[str, list[AlertDestinationGroup]],
        live: bool = True,
        transports: dict[DestinationType, type] | None = None,
    ) -> Any:
        def groups(*, team_id: int, alert_id: str, allowed_event_ids: list[str]) -> list[AlertDestinationGroup]:
            return by_event.get(allowed_event_ids[0], [])

        with (
            patch(f"{_MODULE}.posthoganalytics.feature_enabled", return_value=live),
            patch(f"{_MODULE}.announcement", return_value=announced),
            patch(f"{_MODULE}.list_alert_destination_groups", side_effect=groups),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(f"{_MODULE}._TRANSPORTS", {DestinationType.SLACK: RecordingTransport, **(transports or {})}),
        ):
            return deliver_evaluation(_request(self.team.id))

    def test_a_destination_hears_only_about_the_kinds_it_subscribed_to(self) -> None:
        # One group fires while another resolves. A destination that asked for firings must not
        # be told about the resolve just because the same evaluation produced it.
        announced = _announcement(
            _transition(AlertEventKind.FIRING, "checkout"),
            _transition(AlertEventKind.RESOLVED, "search"),
        )
        fires_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-fires"})
        resolves_only = cast(AlertDestinationData, {**SLACK, "slack_channel_id": "C-resolves"})

        self._run(announced, {FIRING_EVENT: [_group(fires_only)], RESOLVED_EVENT: [_group(resolves_only)]})

        assert sorted((channel, m.headline) for channel, m in RecordingTransport.sends) == [
            ("C-fires", "API errors is firing"),
            ("C-resolves", "API errors is resolved"),
        ]

    def test_a_destination_subscribed_to_both_hears_about_both(self) -> None:
        announced = _announcement(
            _transition(AlertEventKind.FIRING, "checkout"),
            _transition(AlertEventKind.RESOLVED, "search"),
        )

        self._run(announced, {FIRING_EVENT: [_group(SLACK)], RESOLVED_EVENT: [_group(SLACK)]})

        assert sorted(m.headline for _, m in RecordingTransport.sends) == [
            "API errors is firing",
            "API errors is resolved",
        ]

    def test_a_destination_with_no_transport_is_skipped_rather_than_failing_the_send(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            {FIRING_EVENT: [_group(SLACK), _group(UNSUPPORTED)]},
        )

        assert [channel for channel, _ in RecordingTransport.sends] == ["C-1"]
        assert (outcome.sent, outcome.skipped_without_transport) == (1, 1)

    @parameterized.expand(
        [
            ("a_refusal_is_raised_after_the_rest_are_sent", DeliveryError, [WEBHOOK, SLACK]),
            ("a_held_thread_wins_over_a_refusal", ThreadBusy, [WEBHOOK, TEAMS, SLACK]),
        ]
    )
    def test_one_destination_failing_does_not_cost_the_others_their_message(
        self, _name: str, raised: type[Exception], destinations: list[AlertDestinationData]
    ) -> None:
        with pytest.raises(raised, match="status 410"):
            self._run(
                _announcement(_transition(AlertEventKind.FIRING)),
                {FIRING_EVENT: [_group(destination) for destination in destinations]},
                transports={DestinationType.WEBHOOK: RefusingTransport, DestinationType.TEAMS: HeldTransport},
            )

        assert [channel for channel, _ in RecordingTransport.sends] == ["C-1"]

    def test_a_destination_that_is_not_fully_enabled_receives_nothing(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)),
            {FIRING_EVENT: [_group(SLACK, fully_enabled=False)]},
        )

        assert RecordingTransport.sends == []
        assert outcome.sent == 0

    def test_an_evaluation_that_announced_nothing_sends_nothing(self) -> None:
        outcome = self._run(None, {FIRING_EVENT: [_group(SLACK)]})

        assert RecordingTransport.sends == []
        assert outcome.sent == 0

    def test_a_team_without_the_flag_is_not_contacted(self) -> None:
        outcome = self._run(
            _announcement(_transition(AlertEventKind.FIRING)), {FIRING_EVENT: [_group(SLACK)]}, live=False
        )

        assert RecordingTransport.sends == []
        assert outcome.live is False

    def test_the_flag_is_read_against_the_project(self) -> None:
        # Without the project group the condition never matches, and the platform stays silent
        # with nothing to say why.
        with (
            patch(f"{_MODULE}.posthoganalytics.feature_enabled", return_value=False) as flag,
            patch(f"{_MODULE}.announcement", return_value=None),
        ):
            deliver_evaluation(_request(self.team.id))

        assert flag.call_args.args[0] == LIVE_DELIVERY_FLAG
        assert flag.call_args.kwargs["groups"]["project"] == str(self.team.id)

    def test_a_flag_that_cannot_be_read_leaves_the_legacy_path_as_the_only_deliverer(self) -> None:
        with patch(f"{_MODULE}.posthoganalytics.feature_enabled", side_effect=RuntimeError("flags unreachable")):
            outcome = deliver_evaluation(_request(self.team.id))

        assert RecordingTransport.sends == []
        assert outcome.live is False

    def test_the_destination_owner_registers_its_lookup_at_startup(self) -> None:
        # Every other case here patches the lookup, so none of them notices a missing registration.
        assert (
            list_alert_destination_groups(team_id=self.team.id, alert_id="unknown", allowed_event_ids=[FIRING_EVENT])
            == []
        )
