from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from products.alerts_platform.backend.delivery import destinations as destinations_registry
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.api import create_alert_destinations
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    DeliveryTestOutcome,
    DestinationType,
    NewAlertDestination,
    SourceKind,
)
from products.alerts_platform.backend.facade.delivery import delivery_test_destination_ids, send_delivery_test
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import PlatformAlertConfiguration

_TRANSPORTS = "products.alerts_platform.backend.delivery.evaluation._TRANSPORTS"
_LIVE_HOG_FUNCTION = uuid4()


class RecordingTransport:
    """Stands in for Slack at the edge, so the test send stays real up to the provider call."""

    sends: list[tuple[str, AlertMessage]] = []
    provider = "slack"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("slack_channel_id", ""))

    def deliver(
        self, *, team_id: int, target: AlertDestinationData, message: AlertMessage, in_reply_to: Any = None
    ) -> MessageHandle | None:
        if target.get("slack_channel_id") == "C-refuses":
            raise DeliveryError("Slack refused the message: channel_not_found")
        if target.get("slack_channel_id") == "C-slow":
            raise SoftTimeLimitExceeded()
        RecordingTransport.sends.append((self.channel_target(target), message))
        return MessageHandle(external_ref={"channel": self.channel_target(target), "ts": "1"})


def _slack(channel: str) -> AlertDestinationData:
    return cast(
        AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": channel}
    )


class TestDeliveryTestSend(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []

    def _alert(self, owner: PlatformAlertOwner = PlatformAlertOwner.PLATFORM) -> UUID:
        return (
            PlatformAlertConfiguration.objects.for_team(self.team.id)
            .create(
                team=self.team, name="Signups", source_kind=SourceKind.INSIGHT, check_interval_minutes=60, owner=owner
            )
            .id
        )

    def _send(self, alert_id: UUID) -> tuple[frozenset[UUID], DeliveryTestOutcome]:
        def live_ids(*, team_id: int, hog_function_ids: Any) -> frozenset[UUID]:
            return frozenset(hog_function_ids) & {_LIVE_HOG_FUNCTION}

        with (
            patch.dict(_TRANSPORTS, {DestinationType.SLACK: RecordingTransport}),
            patch.object(destinations_registry, "_live_lookup", live_ids),
        ):
            reached = delivery_test_destination_ids(team_id=self.team.id, public_id=alert_id)
            return reached, send_delivery_test(
                team_id=self.team.id,
                public_id=alert_id,
                source=SourceKind.INSIGHT,
                alert_name="Signups dropped",
                source_alert_url="https://app.example.com/alert",
            )

    @parameterized.expand(
        [
            ("row_only", {}, PlatformAlertOwner.PLATFORM, 1),
            ("copies_a_deleted_hog_function", {"legacy_hog_function_ids": (uuid4(),)}, PlatformAlertOwner.PLATFORM, 1),
            (
                "copies_a_live_hog_function",
                {"legacy_hog_function_ids": (_LIVE_HOG_FUNCTION,)},
                PlatformAlertOwner.PLATFORM,
                0,
            ),
            ("disabled", {"enabled": False}, PlatformAlertOwner.PLATFORM, 0),
            ("hears_only_resolves", {"event_kinds": (AlertEventKind.RESOLVED,)}, PlatformAlertOwner.PLATFORM, 0),
            (
                "pagerduty",
                {
                    "data": cast(
                        AlertDestinationData,
                        {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": "a" * 32},
                    ),
                    "event_kinds": (AlertEventKind.FIRING, AlertEventKind.RESOLVED),
                },
                PlatformAlertOwner.PLATFORM,
                0,
            ),
            ("alert_the_source_sends", {}, PlatformAlertOwner.SOURCE, 0),
        ]
    )
    def test_a_delivery_test_reaches_only_rows_that_send_firings_natively(
        self, _name: str, overrides: dict[str, Any], owner: PlatformAlertOwner, sends: int
    ) -> None:
        alert_id = self._alert(owner)
        (row,) = create_alert_destinations(
            team_id=self.team.id,
            configuration_id=alert_id,
            destinations=(
                NewAlertDestination(
                    **{"data": _slack("C-alerts"), "event_kinds": (AlertEventKind.FIRING,), **overrides}
                ),
            ),
        )

        reached, outcome = self._send(alert_id)

        assert (len(reached), outcome) == (sends, DeliveryTestOutcome(sent=sends, failed=0))
        assert reached == ({row.id} if sends else frozenset())
        assert [
            (channel, message.headline, message.context, message.alert_url, message.labels)
            for channel, message in RecordingTransport.sends
        ] == [
            (
                "C-alerts",
                "Insight alert '[TEST] Signups dropped' is firing",
                ("Test alert from PostHog. No action is needed.",),
                "https://app.example.com/alert",
                {"posthog_delivery_test": "true"},
            )
        ] * sends
        # A firing of an ungrouped alert has an empty group, which a test must not share.
        assert all(message.transition.grouping_key for _, message in RecordingTransport.sends)

    def test_a_destination_that_refuses_the_test_does_not_stop_the_others(self) -> None:
        alert_id = self._alert()
        create_alert_destinations(
            team_id=self.team.id,
            configuration_id=alert_id,
            destinations=tuple(
                NewAlertDestination(data=_slack(channel), event_kinds=(AlertEventKind.FIRING,))
                for channel in ("C-refuses", "C-alerts")
            ),
        )

        _, outcome = self._send(alert_id)

        assert outcome == DeliveryTestOutcome(sent=1, failed=1)
        assert [channel for channel, _ in RecordingTransport.sends] == ["C-alerts"]

    def test_the_task_time_limit_ends_the_test_rather_than_skipping_to_the_next_destination(self) -> None:
        alert_id = self._alert()
        create_alert_destinations(
            team_id=self.team.id,
            configuration_id=alert_id,
            destinations=tuple(
                NewAlertDestination(data=_slack(channel), event_kinds=(AlertEventKind.FIRING,))
                for channel in ("C-slow", "C-alerts")
            ),
        )

        with pytest.raises(SoftTimeLimitExceeded):
            self._send(alert_id)

        assert RecordingTransport.sends == []
