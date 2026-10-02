from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import patch

from django.test import SimpleTestCase

from products.alerts.backend.delivery.evaluation import DESTINATIONS_ARE_LIVE, deliver_evaluation
from products.alerts.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertDestinationGroup,
    AlertEventKind,
    AnnouncedTransition,
    DestinationType,
    EvaluationAnnouncement,
    SourceKind,
)

_MODULE = "products.alerts.backend.delivery.evaluation"
FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)

SLACK = cast(AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-1"})
WEBHOOK = cast(AlertDestinationData, {"type": DestinationType.WEBHOOK, "webhook_url": "https://example.com/hook"})


def _request() -> AlertDeliveryRequest:
    return AlertDeliveryRequest(
        source=SourceKind.LOGS,
        team_id=2,
        configuration_id="cfg-1",
        evaluation_key="eval-1",
        destination_alert_id="legacy-1",
        event_ids_by_kind={"firing": "$logs_alert_firing", "resolved": "$logs_alert_resolved"},
    )


def _announcement(*kinds: AlertEventKind) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(
        alert_name="API errors",
        consecutive_failures=0,
        transitions=tuple(
            AnnouncedTransition(
                grouping_key="",
                kind=kind,
                episode_started_at=FIRING,
                value=None,
                labels={},
                condition={},
                source_config={},
                error_message=None,
            )
            for kind in kinds
        ),
    )


def _group(data: AlertDestinationData, fully_enabled: bool = True) -> AlertDestinationGroup:
    return AlertDestinationGroup(hog_function_ids=(), data=data, fully_enabled=fully_enabled)


class TestDeliverEvaluation(SimpleTestCase):
    def _run(self, announced: Any, groups: list[AlertDestinationGroup]) -> Any:
        with (
            patch(f"{_MODULE}.announcement", return_value=announced),
            patch(f"{_MODULE}.list_alert_destination_groups", return_value=groups) as resolved,
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch(f"{_MODULE}.deliver") as delivered,
        ):
            outcome = deliver_evaluation(_request())
        return outcome, resolved, delivered

    def test_a_destination_with_no_transport_is_skipped_rather_than_failing_the_send(self) -> None:
        outcome, _, delivered = self._run(_announcement(AlertEventKind.FIRING), [_group(SLACK), _group(WEBHOOK)])

        assert [call.kwargs["target"] for call in delivered.call_args_list] == [SLACK]
        assert (outcome.sent, outcome.skipped_without_transport) == (1, 1)

    def test_a_destination_that_is_not_fully_enabled_receives_nothing(self) -> None:
        outcome, _, delivered = self._run(_announcement(AlertEventKind.FIRING), [_group(SLACK, fully_enabled=False)])

        assert delivered.call_args_list == []
        assert outcome.sent == 0

    def test_only_the_kinds_this_evaluation_announced_decide_who_hears_about_it(self) -> None:
        # A destination configured for firings only must not receive a resolve, so the lookup
        # asks for the event ids of the kinds actually announced rather than all of them.
        _, resolved, _ = self._run(_announcement(AlertEventKind.RESOLVED), [_group(SLACK)])

        assert resolved.call_args.kwargs["allowed_event_ids"] == ["$logs_alert_resolved"]

    def test_an_evaluation_that_announced_nothing_resolves_no_destinations(self) -> None:
        outcome, resolved, delivered = self._run(None, [_group(SLACK)])

        assert resolved.call_args_list == []
        assert delivered.call_args_list == []
        assert outcome.sent == 0

    def test_destinations_are_not_live(self) -> None:
        # The parallel run notifies through the logs product's own stack. Flipping this before
        # a team is cut over means every logs alert notifies twice.
        assert DESTINATIONS_ARE_LIVE is False
