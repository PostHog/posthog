from dataclasses import replace
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.delivery import routing
from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.routing import deliver_routes
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError, DestinationRefused, RefusedEverywhere
from products.alerts_platform.backend.facade.contracts import (
    ROUTING_FLAG,
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
    IncidentAction,
    SourceKind,
)
from products.alerts_platform.backend.logic.platform_alert_events import AnnouncementRead, AnnouncementStatus
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute, PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.temporal.web_start import deliver_inline
from products.alerts_platform.backend.tests.test_delivery_evaluation import (
    CONFIGURATION_ID,
    PAGERDUTY,
    SLACK,
    PagingTransport,
    RecordingTransport,
    _announcement,
    _request,
    _transition,
)

_MODULE = "products.alerts_platform.backend.delivery.routing"
_WEB_START = "products.alerts_platform.backend.temporal.web_start"


class TestDeliverRoutes(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []
        PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            id=CONFIGURATION_ID,
            team=self.team,
            name="API errors",
            source_kind=SourceKind.LOGS,
            check_interval_minutes=5,
            labels={"team": "infra"},
            annotations={"runbook": "https://example.com/runbook"},
        )
        self._route("C-infra", [{"label": "team", "op": "=", "value": "infra"}], 0)
        self._route("C-billing", [{"label": "team", "op": "=", "value": "billing"}], 1)
        self._route("C-all", [], 2)

    def _route(
        self,
        channel: str,
        matchers: list[dict[str, str]],
        position: int,
        config: AlertDestinationData = SLACK,
        event_kinds: tuple[str, ...] = ("firing",),
    ) -> None:
        target = (
            {**config, "slack_channel_id": channel}
            if config["type"] == DestinationType.SLACK
            else {**config, "pagerduty_routing_key": channel}
        )
        receiver = AlertReceiver.objects.for_team(self.team.id).create(
            team=self.team, name=channel, type=config["type"], config=cast(AlertDestinationData, target)
        )
        AlertRoute.objects.for_team(self.team.id).create(
            team=self.team, receiver=receiver, matchers=matchers, event_kinds=list(event_kinds), position=position
        )

    def _deliver(
        self,
        flag: Any = True,
        *,
        transitions: tuple[Any, ...] = (_transition(AlertEventKind.FIRING),),
        sends_messages: bool = True,
        incident_actions: dict[str, IncidentAction] | None = None,
        inline: bool = False,
    ) -> int:
        def feature_enabled(key: str, *args: Any, **kwargs: Any) -> Any:
            if isinstance(flag, Exception):
                raise flag
            return flag if key == ROUTING_FLAG else False

        request = _request(
            self.team.id, owned_by_platform=True, sends_messages=sends_messages, incident_actions=incident_actions
        )
        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=feature_enabled,
            ),
            patch(
                "products.alerts_platform.backend.logic.platform_alert_events._read_evaluation",
                return_value=AnnouncementRead(
                    status=AnnouncementStatus.FOUND, announcement=_announcement(*transitions)
                ),
            ),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(
                f"{_MODULE}._TRANSPORTS",
                {DestinationType.SLACK: RecordingTransport, DestinationType.PAGERDUTY: PagingTransport},
            ),
        ):
            if not inline:
                return deliver_routes(request)
            # The alert's own destinations are covered by the evaluation tests; this checks the routed sends.
            with patch(f"{_WEB_START}.deliver_evaluation"):
                deliver_inline(request)
            return len(RecordingTransport.sends)

    @parameterized.expand(
        [
            ("routing_on", True, ["C-infra", "C-all"]),
            ("routing_off", False, []),
            ("flag_check_fails", RuntimeError("flags down"), []),
            ("flag_lookup_swallowed", None, []),
        ]
    )
    def test_sends_to_the_receivers_whose_routes_match_the_labels(
        self, _name: str, flag: Any, expected_channels: list[str]
    ) -> None:
        sent = self._deliver(flag)

        assert [channel for channel, _ in RecordingTransport.sends] == expected_channels
        assert sent == len(expected_channels)
        for _, message in RecordingTransport.sends:
            assert message.rule_details == (
                MessageDetail(label="team", value="infra"),
                MessageDetail(label="runbook", value="https://example.com/runbook"),
            )

    def test_routes_each_group_on_its_own_labels_under_the_rules(self) -> None:
        self._route(
            "C-rotation-a", [{"label": "rotation", "op": "=", "value": "a"}], 3, event_kinds=("firing", "resolved")
        )
        self._route("C-rotation-b", [{"label": "rotation", "op": "=", "value": "b"}], 4)
        PlatformAlert.objects.for_team(self.team.id).create(
            team=self.team, configuration_id=CONFIGURATION_ID, grouping_key="gone", labels={"rotation": "a"}
        )
        groups = (
            replace(_transition(AlertEventKind.FIRING, "a"), labels={"rotation": "a"}),
            replace(_transition(AlertEventKind.FIRING, "b"), labels={"rotation": "b"}),
            replace(_transition(AlertEventKind.FIRING, "billing"), labels={"team": "billing"}),
            # A group the check stopped returning resolves without labels, routed on its stored ones.
            _transition(AlertEventKind.RESOLVED, "gone"),
        )

        sent = self._deliver(transitions=groups)

        heard = [(channel, message.labels.get("rotation", "-")) for channel, message in RecordingTransport.sends]
        assert heard == [
            ("C-infra", "a"),
            ("C-infra", "b"),
            ("C-infra", "-"),
            ("C-all", "a"),
            ("C-all", "b"),
            ("C-all", "-"),
            ("C-rotation-a", "a"),
            ("C-rotation-a", "-"),
            ("C-rotation-b", "b"),
        ]
        assert sent == 4

    @parameterized.expand(
        [
            ("busy", ThreadBusy("1 of 1 threads are held by another send")),
            ("failed", DeliveryError("slack returned 500")),
        ]
    )
    def test_one_receiver_failing_still_sends_the_rest_then_raises_for_a_retry(
        self, _name: str, error: Exception
    ) -> None:
        real_deliver = routing.deliver

        def deliver(**kwargs: Any) -> Any:
            if kwargs["target"]["slack_channel_id"] == "C-infra":
                raise error
            return real_deliver(**kwargs)

        with patch(f"{_MODULE}.deliver", side_effect=deliver), pytest.raises(type(error)):
            self._deliver()

        assert [channel for channel, _ in RecordingTransport.sends] == ["C-all"]

    @parameterized.expand(
        [
            # The route lists only errored, which a pager must not take as a reason to miss a trigger.
            (
                "opens_and_closes_alongside_messages",
                True,
                {"checkout": IncidentAction.TRIGGER, "search": IncidentAction.RESOLVE},
                ["C-infra", "C-all", "P-infra", "P-infra"],
                [None, None, IncidentAction.TRIGGER, IncidentAction.RESOLVE],
            ),
            # Cooldown held the announcement, so chat receivers hear nothing, but the incident still moves.
            (
                "held_announcement_still_moves_the_incident",
                False,
                {"checkout": IncidentAction.TRIGGER},
                ["P-infra"],
                [IncidentAction.TRIGGER],
            ),
            ("no_incident_edge", True, {}, ["C-infra", "C-all"], [None, None]),
            # Deleting a firing alert sends its resolve inline, before the alert and its labels are gone.
            (
                "inline_resolve_before_a_delete",
                False,
                {"search": IncidentAction.RESOLVE},
                ["P-infra"],
                [IncidentAction.RESOLVE],
            ),
        ]
    )
    def test_an_incident_receiver_hears_every_trigger_and_resolve_and_chat_receivers_only_messages(
        self,
        _name: str,
        sends_messages: bool,
        incident_actions: dict[str, IncidentAction],
        expected_targets: list[str],
        expected_actions: list[IncidentAction | None],
    ) -> None:
        self._route("P-infra", [{"label": "team", "op": "=", "value": "infra"}], 3, PAGERDUTY, ("errored",))

        self._deliver(
            transitions=(
                _transition(AlertEventKind.FIRING, "checkout"),
                _transition(AlertEventKind.RESOLVED, "search"),
            ),
            sends_messages=sends_messages,
            incident_actions=incident_actions,
            inline=_name.startswith("inline"),
        )

        assert [target for target, _ in RecordingTransport.sends] == expected_targets
        assert [message.incident_action for _, message in RecordingTransport.sends] == expected_actions

    @parameterized.expand(
        [
            ("flag_check_fails", RuntimeError("flags down"), True),
            ("flag_lookup_swallowed", None, True),
            # Routing has nothing to send, so a flag blip must not fail the delivery.
            ("pagerduty_receiver_without_a_route", None, False),
        ]
    )
    def test_a_routed_resolve_is_retried_when_the_flag_cannot_be_read(
        self, _name: str, flag: Any, routed: bool
    ) -> None:
        self._route("P-infra", [{"label": "team", "op": "=", "value": "infra"}], 3, PAGERDUTY)
        if not routed:
            AlertRoute.objects.for_team(self.team.id).filter(receiver__type=DestinationType.PAGERDUTY).delete()

        def deliver() -> int:
            return self._deliver(
                flag,
                transitions=(_transition(AlertEventKind.RESOLVED, "search"),),
                sends_messages=not routed,
                incident_actions={"search": IncidentAction.RESOLVE},
            )

        if routed:
            with pytest.raises(DeliveryError) as raised:
                deliver()
            assert not isinstance(raised.value, RefusedEverywhere)
        else:
            assert deliver() == 0
        assert RecordingTransport.sends == []

    @parameterized.expand([("every_receiver_refused", True), ("a_receiver_timed_out_too", False)])
    def test_receivers_that_all_refused_are_not_retried(self, _name: str, permanent: bool) -> None:
        def deliver(**kwargs: Any) -> Any:
            if kwargs["target"]["slack_channel_id"] == "C-infra" or permanent:
                raise DestinationRefused("Slack refused the message: not_in_channel.")
            raise DeliveryError("Slack's answer was lost: TimeoutError")

        with patch(f"{_MODULE}.deliver", side_effect=deliver), pytest.raises(DeliveryError) as raised:
            self._deliver()

        assert isinstance(raised.value, RefusedEverywhere) is permanent

    def test_a_refused_trigger_still_lets_the_resolve_of_another_group_through(self) -> None:
        self._route("P-infra", [{"label": "team", "op": "=", "value": "infra"}], 3, PAGERDUTY)
        real_deliver = routing.deliver

        def deliver(**kwargs: Any) -> Any:
            if kwargs["incident_action"] == IncidentAction.TRIGGER:
                raise DestinationRefused("PagerDuty refused the event with status 400.")
            return real_deliver(**kwargs)

        with patch(f"{_MODULE}.deliver", side_effect=deliver), pytest.raises(RefusedEverywhere):
            self._deliver(
                transitions=(
                    _transition(AlertEventKind.FIRING, "checkout"),
                    _transition(AlertEventKind.RESOLVED, "search"),
                ),
                sends_messages=False,
                incident_actions={"checkout": IncidentAction.TRIGGER, "search": IncidentAction.RESOLVE},
            )

        assert [(target, message.incident_action) for target, message in RecordingTransport.sends] == [
            ("P-infra", IncidentAction.RESOLVE)
        ]
