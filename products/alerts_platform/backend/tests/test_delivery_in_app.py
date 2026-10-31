from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.user import User

from products.alerts_platform.backend.delivery.in_app import InAppTransport
from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind, DestinationType
from products.alerts_platform.backend.tests.delivery_messages import OCCURRED, alert_message, announced_transition
from products.notifications.backend.facade.testing import stored_notifications_for_team


class TestInAppTransport(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        self.other_user = User.objects.create_and_join(self.organization, "other@example.com", None)

    def _deliver(self, kind: AlertEventKind, **transition: Any) -> None:
        target: AlertDestinationData = {
            "type": DestinationType.IN_APP,
            "in_app_user_ids": [self.user.id, self.other_user.id],
            "in_app_resource_type": "insight",
            "in_app_resource_id": "abc123",
            "in_app_url": "/project/1/insights/abc123",
        }
        message = alert_message(
            headline="Insight alert 'API errors' is firing",
            details=(MessageDetail(label="Value", value="312"), MessageDetail(label="Threshold", value="> 300")),
            transition=announced_transition(kind, **transition),
        )
        assert InAppTransport().deliver(team_id=self.team.id, target=target, message=message) is None

    @parameterized.expand(
        [
            ("firing", AlertEventKind.FIRING, "alert_firing"),
            ("errored", AlertEventKind.ERRORED, "pipeline_failure"),
        ]
    )
    def test_a_retry_notifies_nobody_twice_and_a_later_transition_notifies_again(
        self, _name: str, kind: AlertEventKind, notification_type: str
    ) -> None:
        self._deliver(kind)
        self._deliver(kind)

        events = stored_notifications_for_team(self.team.id)
        assert sorted(user_id for event in events for user_id in event.resolved_user_ids) == sorted(
            [self.user.id, self.other_user.id]
        )
        assert {
            (event.notification_type, event.title, event.body, event.resource_id, event.source_url) for event in events
        } == {
            (
                notification_type,
                "Insight alert 'API errors' is firing",
                "Value: 312; Threshold: > 300",
                "abc123",
                "/project/1/insights/abc123",
            )
        }

        self._deliver(kind, occurred_at=OCCURRED + timedelta(hours=1))

        assert len(stored_notifications_for_team(self.team.id)) == 4
