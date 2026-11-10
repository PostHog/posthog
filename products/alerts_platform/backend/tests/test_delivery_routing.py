from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts_platform.backend.delivery import routing
from products.alerts_platform.backend.delivery.routing import ROUTING_FLAG, deliver_routes
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
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

_MODULE = "products.alerts_platform.backend.delivery.routing"


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
            destinations_owner=PlatformAlertOwner.PLATFORM,
            labels={"team": "infra"},
        )
        self._route("C-infra", [{"label": "team", "op": "=", "value": "infra"}], 0)
        self._route("C-billing", [{"label": "team", "op": "=", "value": "billing"}], 1)
        self._route("C-all", [], 2)

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

    def _deliver(self, flag: Any = True) -> int:
        def feature_enabled(key: str, *args: Any, **kwargs: Any) -> Any:
            if isinstance(flag, Exception):
                raise flag
            return flag if key == ROUTING_FLAG else False

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=feature_enabled,
            ),
            patch(f"{_MODULE}.announcement", return_value=_announcement(_transition(AlertEventKind.FIRING))),
            patch(f"{_MODULE}.DatabaseThreadStore"),
            patch.dict(f"{_MODULE}._TRANSPORTS", {DestinationType.SLACK: RecordingTransport}),
        ):
            return deliver_routes(_request(self.team.id, owned_by_platform=True))

    @parameterized.expand(
        [
            ("routing_on", True, ["C-infra", "C-all"]),
            ("routing_off", False, []),
            ("flag_check_fails", RuntimeError("flags down"), []),
        ]
    )
    def test_sends_to_the_receivers_whose_routes_match_the_labels(
        self, _name: str, flag: Any, expected_channels: list[str]
    ) -> None:
        sent = self._deliver(flag)

        assert [channel for channel, _ in RecordingTransport.sends] == expected_channels
        assert sent == len(expected_channels)

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
