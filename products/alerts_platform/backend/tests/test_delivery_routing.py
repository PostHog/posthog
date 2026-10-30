from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.delivery import delivery_paths
from products.alerts_platform.backend.delivery.evaluation import deliver_evaluation
from products.alerts_platform.backend.delivery.routing import ROUTING_FLAG
from products.alerts_platform.backend.facade.api import create_alert_destinations
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import AlertReceiver, AlertRoute, PlatformAlertConfiguration
from products.alerts_platform.backend.tests.test_delivery_evaluation import (
    CONFIGURATION_ID,
    SLACK,
    RecordingTransport,
    _announcement,
    _request,
    _transition,
)

_MODULE = "products.alerts_platform.backend.delivery.evaluation"


class TestDeliverRoutes(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []
        configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            id=CONFIGURATION_ID,
            team=self.team,
            name="API errors",
            source_kind=SourceKind.LOGS,
            check_interval_minutes=5,
            destinations_owner=PlatformAlertOwner.PLATFORM,
            labels={"team": "infra"},
        )
        create_alert_destinations(
            team_id=self.team.id,
            configuration_id=configuration.id,
            destinations=(NewAlertDestination(data=SLACK, event_kinds=(AlertEventKind.FIRING,)),),
        )

    def _route(self, channel: str, matchers: list[dict[str, str]], position: int) -> None:
        receiver = AlertReceiver.objects.for_team(self.team.id).create(
            team=self.team,
            name=channel,
            type=DestinationType.SLACK,
            config=cast(AlertDestinationData, {**SLACK, "slack_channel_id": channel}),
        )
        AlertRoute.objects.for_team(self.team.id).create(
            team=self.team, receiver=receiver, matchers=matchers, event_kinds=["firing"], position=position
        )

    def _deliver(self, flags: dict[str, Any]) -> None:
        def feature_enabled(flag: str, *args: Any, **kwargs: Any) -> Any:
            value = flags.get(flag, False)
            if isinstance(value, Exception):
                raise value
            return value

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=feature_enabled,
            ),
            patch(f"{_MODULE}.announcement", return_value=_announcement(_transition(AlertEventKind.FIRING))),
            patch(f"{_MODULE}.announced_kinds", return_value={}),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(delivery_paths._emitters, clear=True),
            patch.dict(f"{_MODULE}._TRANSPORTS", {DestinationType.SLACK: RecordingTransport}),
        ):
            deliver_evaluation(_request(self.team.id, owned_by_platform=True))

    @parameterized.expand(
        [
            ("routing_on", {ROUTING_FLAG: True}, ["C-1", "C-infra", "C-all"]),
            ("routing_off", {ROUTING_FLAG: False}, ["C-1"]),
            ("flag_check_fails", {ROUTING_FLAG: RuntimeError("flags down")}, ["C-1"]),
        ]
    )
    def test_matching_routes_send_beside_the_alert_own_destinations(
        self, _name: str, flags: dict[str, Any], expected_channels: list[str]
    ) -> None:
        self._route("C-infra", [{"label": "team", "op": "=", "value": "infra"}], 0)
        self._route("C-billing", [{"label": "team", "op": "=", "value": "billing"}], 1)
        self._route("C-all", [], 2)

        self._deliver(flags)

        assert [channel for channel, _ in RecordingTransport.sends] == expected_channels
