from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import MessageHandle
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import create_alert_destinations, record_verdict_change
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    SourceKind,
    VerdictChange,
    VerdictChangeNotRecorded,
)
from products.alerts_platform.backend.facade.enums import HoldRelease, PlatformAlertOwner
from products.alerts_platform.backend.logic.platform_lifecycle import event_row, record_history
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration, PlatformAlertDeliveryHold

FIRING_AT = datetime(2026, 10, 19, 9, tzinfo=UTC)
FIRING_KEY = f"slot:{FIRING_AT.isoformat()}"
FIRING_EVENT = "$metrics_alert_firing"
SLACK = cast(AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": "C-1"})


class ThreadedTransport:
    sends: list[tuple[AlertMessage, MessageHandle | None]] = []
    provider = "slack"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("slack_channel_id", ""))

    def deliver(
        self, *, team_id: int, target: AlertDestinationData, message: AlertMessage, in_reply_to: Any = None
    ) -> MessageHandle | None:
        ThreadedTransport.sends.append((message, in_reply_to))
        return MessageHandle(external_ref={"ts": str(len(ThreadedTransport.sends))})


class TestRecordVerdictChange(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        ThreadedTransport.sends = []
        self.next_check_at = FIRING_AT + timedelta(minutes=5)
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="Checkout latency",
                source_kind=PlatformAlertConfiguration.SourceKind.METRICS,
                source_config={},
                check_interval_minutes=5,
                next_check_at=self.next_check_at,
                owner=PlatformAlertOwner.PLATFORM,
                destinations_owner=PlatformAlertOwner.PLATFORM,
            )
            platform_testing.start_firing(self.configuration.id, team_id=self.team.id, at=FIRING_AT)
            PlatformAlert.objects.filter(configuration=self.configuration).update(last_notified_at=FIRING_AT)
        create_alert_destinations(
            team_id=self.team.id,
            configuration_id=self.configuration.id,
            destinations=(NewAlertDestination(data=SLACK, event_kinds=(AlertEventKind.FIRING,)),),
        )

    def _deliver(self, request: AlertDeliveryRequest) -> None:
        with patch.dict(
            "products.alerts_platform.backend.delivery.evaluation._TRANSPORTS",
            {DestinationType.SLACK: ThreadedTransport},
        ):
            platform_testing.deliver(request)

    def test_a_follow_up_replies_once_in_the_thread_of_the_firing_it_follows(self) -> None:
        with team_scope(self.team.id):
            alert = PlatformAlert.objects.get(configuration=self.configuration)
            firing_row = event_row(
                self.configuration,
                alert=alert,
                evaluation_key=FIRING_KEY,
                kind=AlertEventKind.FIRING.value,
                previous_state="not_firing",
                state="firing",
                episode_started_at=FIRING_AT,
                consecutive_failures=0,
                now=FIRING_AT,
            )
        record_history(self.team.id, [firing_row])
        self._deliver(
            AlertDeliveryRequest(
                source=SourceKind.METRICS,
                team_id=self.team.id,
                configuration_id=str(self.configuration.id),
                evaluation_key=FIRING_KEY,
                destination_alert_id=str(self.configuration.id),
                event_ids_by_kind={AlertEventKind.FIRING.value: FIRING_EVENT},
                owned_by_platform=True,
            )
        )

        with team_scope(self.team.id):
            follow_up = record_verdict_change(
                VerdictChange(
                    team_id=self.team.id,
                    configuration_id=self.configuration.id,
                    firing_evaluation_key=FIRING_KEY,
                    episode_started_at=FIRING_AT,
                    firing_event_id=FIRING_EVENT,
                ),
                now=FIRING_AT + timedelta(minutes=20),
            )
        assert follow_up is not None
        self._deliver(follow_up)
        self._deliver(follow_up)

        [(firing, opened_in), (reply, replied_to)] = ThreadedTransport.sends
        assert (firing.transition.kind, opened_in) == (AlertEventKind.FIRING, None)
        assert reply.headline == "Metric alert 'Checkout latency' has a new verdict"
        assert replied_to == MessageHandle(external_ref={"ts": "1"})
        with team_scope(self.team.id):
            configuration = PlatformAlertConfiguration.objects.get(id=self.configuration.id)
            alert = PlatformAlert.objects.get(configuration=self.configuration)
        assert (configuration.next_check_at, alert.state, alert.last_notified_at) == (
            self.next_check_at,
            "firing",
            FIRING_AT,
        )

    @parameterized.expand([("still_held", None), ("suppressed", HoldRelease.SUPPRESS)])
    def test_a_firing_nobody_received_gets_no_follow_up(self, _name: str, release: HoldRelease | None) -> None:
        with team_scope(self.team.id):
            PlatformAlertDeliveryHold.objects.create(
                team=self.team,
                configuration=self.configuration,
                evaluation_key=FIRING_KEY,
                reason="investigation",
                request={},
                held_at=FIRING_AT,
                release_after=FIRING_AT + timedelta(minutes=90),
                released_at=FIRING_AT if release else None,
                release_action=release,
            )
            follow_up = record_verdict_change(
                VerdictChange(
                    team_id=self.team.id,
                    configuration_id=self.configuration.id,
                    firing_evaluation_key=FIRING_KEY,
                    episode_started_at=FIRING_AT,
                    firing_event_id=FIRING_EVENT,
                ),
                now=FIRING_AT + timedelta(minutes=20),
            )

        assert follow_up is None

    def test_a_follow_up_clickhouse_refused_raises_so_the_caller_can_retry(self) -> None:
        with (
            team_scope(self.team.id),
            patch("products.alerts_platform.backend.logic.platform_lifecycle.insert_events", return_value=0),
            pytest.raises(VerdictChangeNotRecorded),
        ):
            record_verdict_change(
                VerdictChange(
                    team_id=self.team.id,
                    configuration_id=self.configuration.id,
                    firing_evaluation_key=FIRING_KEY,
                    episode_started_at=FIRING_AT,
                    firing_event_id=FIRING_EVENT,
                ),
                now=FIRING_AT + timedelta(minutes=20),
            )

    def test_a_grouped_follow_up_names_its_group(self) -> None:
        change = VerdictChange(
            team_id=self.team.id,
            configuration_id=self.configuration.id,
            firing_evaluation_key=FIRING_KEY,
            episode_started_at=FIRING_AT,
            firing_event_id=FIRING_EVENT,
            grouping_key="checkout",
        )
        with team_scope(self.team.id):
            platform_testing.start_firing(
                self.configuration.id, team_id=self.team.id, at=FIRING_AT, grouping_key="checkout"
            )
            PlatformAlert.objects.filter(configuration=self.configuration, grouping_key="checkout").update(
                labels={"service_name": "checkout"}
            )
            with patch(
                "products.alerts_platform.backend.logic.verdict_changes.record_history", return_value=1
            ) as recorded:
                follow_up = record_verdict_change(change, now=FIRING_AT + timedelta(minutes=20))

        [[_team_id, [row]], _] = recorded.call_args
        assert (row.grouping_key, row.labels, row.evaluation_key) == (
            "checkout",
            {"service_name": "checkout"},
            change.evaluation_key,
        )
        assert follow_up is not None and follow_up.evaluation_key == change.evaluation_key


class TestVerdictChangeKey(SimpleTestCase):
    def test_each_group_gets_a_key_that_fits_a_thread(self) -> None:
        def key(grouping_key: str) -> str:
            return VerdictChange(
                team_id=1,
                configuration_id=uuid4(),
                firing_evaluation_key=FIRING_KEY,
                episode_started_at=FIRING_AT,
                firing_event_id=FIRING_EVENT,
                grouping_key=grouping_key,
            ).evaluation_key

        longest = key("a" * 255)

        assert len(longest) <= 255
        assert longest != key("a" * 254 + "b")
        assert key("") == f"{FIRING_KEY}#verdict"
