from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.subscription import Subscription

from ee.tasks.subscriptions.auto_disable import SLACK_INTEGRATION_DISCONNECTED_REASON, disable_invalid_subscription


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
        sub = self._make_subscription()

        with patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock:
            disable_invalid_subscription(sub, SLACK_INTEGRATION_DISCONNECTED_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_called_once_with(sub, SLACK_INTEGRATION_DISCONNECTED_REASON, [self.user.email])

    @parameterized.expand(
        [
            ("no_creator", False),
            ("creator_with_empty_email", True),
        ]
    )
    def test_no_email_when_creator_unable_to_receive(self, _label, use_creator_with_empty_email):
        if use_creator_with_empty_email:
            self.user.email = ""
            self.user.save()
            sub = self._make_subscription(created_by=self.user)
        else:
            sub = self._make_subscription(created_by=None)

        with patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock:
            disable_invalid_subscription(sub, SLACK_INTEGRATION_DISCONNECTED_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_not_called()
