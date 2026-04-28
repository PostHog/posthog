from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.subscription import Subscription


class TestDisableInvalidSubscription(APIBaseTest):
    def _make_subscription(self, **overrides) -> Subscription:
        defaults = {
            "team": self.team,
            "target_type": "slack",
            "target_value": "C12345",
            "frequency": "daily",
            "start_date": timezone.now(),
            "insight": None,
            "title": "t",
            "created_by": self.user,
            "enabled": True,
        }
        defaults.update(overrides)
        return Subscription.objects.create(**defaults)

    def test_disables_subscription(self):
        from ee.tasks.subscriptions.auto_disable import disable_invalid_subscription

        sub = self._make_subscription()

        with patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock:
            disable_invalid_subscription(sub, "Slack integration disconnected")

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_called_once()

    def test_no_email_when_no_creator(self):
        from ee.tasks.subscriptions.auto_disable import disable_invalid_subscription

        sub = self._make_subscription(created_by=None)

        with patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock:
            disable_invalid_subscription(sub, "Slack integration disconnected")

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_not_called()
