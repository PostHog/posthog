import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.exports.backend.models.subscription import Subscription

from ee.tasks.subscriptions.failure_notifications import (
    EMAIL_FAILURE_REASON,
    GENERIC_FAILURE_REASON,
    SLACK_FAILURE_REASON,
    classify_delivery_failure,
    failure_target_label,
    send_notification_for_failed_subscription,
)


class TestClassifyDeliveryFailure:
    @parameterized.expand(
        [
            ("slack", "slack", SLACK_FAILURE_REASON),
            ("email", "email", EMAIL_FAILURE_REASON),
            ("unknown_target", "webhook", GENERIC_FAILURE_REASON),
            ("none_target", None, GENERIC_FAILURE_REASON),
        ]
    )
    def test_classify_delivery_failure(self, _label, target_type, expected):
        reason = classify_delivery_failure(target_type)
        assert reason == expected
        # Every reason carries an actionable suggestion so the email is never a dead end.
        assert reason.summary
        assert reason.suggestion


class TestFailureTargetLabel(APIBaseTest):
    def _make_subscription(self, **overrides) -> Subscription:
        defaults = {
            "team": self.team,
            "target_type": "slack",
            "target_value": "C12345|#alerts",
            "frequency": "daily",
            "start_date": timezone.now(),
            "insight": None,
            "title": "t",
            "created_by": self.user,
        }
        defaults.update(overrides)
        return Subscription.objects.create(**defaults)

    @parameterized.expand(
        [
            ("slack_id_and_name", "slack", "C12345|#alerts", "#alerts"),
            ("slack_name_without_hash", "slack", "C12345|alerts", "#alerts"),
            ("slack_id_only", "slack", "C12345", None),
            ("email_single", "email", "a@b.com", "a@b.com"),
            ("email_multiple", "email", "a@b.com,c@d.com", "a@b.com,c@d.com"),
            ("empty", "slack", "", None),
        ]
    )
    def test_failure_target_label(self, _label, target_type, target_value, expected):
        sub = self._make_subscription(target_type=target_type, target_value=target_value)
        assert failure_target_label(sub) == expected


class TestSendNotificationForFailedSubscription(APIBaseTest):
    def _make_subscription(self, **overrides) -> Subscription:
        defaults = {
            "team": self.team,
            "target_type": "slack",
            "target_value": "C12345|#alerts",
            "frequency": "daily",
            "start_date": timezone.now(),
            "insight": None,
            "title": "Daily metrics",
            "created_by": self.user,
        }
        defaults.update(overrides)
        return Subscription.objects.create(**defaults)

    def test_builds_email_with_failure_context(self):
        sub = self._make_subscription()

        with patch("ee.tasks.subscriptions.failure_notifications.EmailMessage") as email_cls:
            send_notification_for_failed_subscription(
                sub, SLACK_FAILURE_REASON, "SlackApiError", uuid.uuid4(), [self.user.email]
            )

        kwargs = email_cls.call_args.kwargs
        assert kwargs["template_name"] == "subscription_failed"
        assert "Daily metrics" in kwargs["subject"]
        ctx = kwargs["template_context"]
        assert ctx["subscription_title"] == "Daily metrics"
        assert ctx["target_label"] == "#alerts"
        assert ctx["failure_summary"] == SLACK_FAILURE_REASON.summary
        assert ctx["failure_suggestion"] == SLACK_FAILURE_REASON.suggestion
        assert ctx["error_type"] == "SlackApiError"
        email_cls.return_value.add_recipient.assert_called_once_with(email=self.user.email)
        email_cls.return_value.send.assert_called_once()

    def test_untitled_subscription_uses_generic_copy(self):
        sub = self._make_subscription(title=None)

        with patch("ee.tasks.subscriptions.failure_notifications.EmailMessage") as email_cls:
            send_notification_for_failed_subscription(
                sub, GENERIC_FAILURE_REASON, None, uuid.uuid4(), [self.user.email]
            )

        kwargs = email_cls.call_args.kwargs
        assert kwargs["subject"] == "Your PostHog subscription failed to send"
        assert kwargs["template_context"]["subscription_title"] == "your subscription"

    def test_campaign_key_is_idempotent_per_delivery(self):
        # Keyed on the delivery id so a Temporal activity retry reuses the key (and
        # MessagingRecord dedups), while distinct deliveries still get distinct keys.
        sub = self._make_subscription()
        delivery_id = uuid.uuid4()

        with patch("ee.tasks.subscriptions.failure_notifications.EmailMessage") as email_cls:
            send_notification_for_failed_subscription(sub, SLACK_FAILURE_REASON, None, delivery_id, [self.user.email])
            send_notification_for_failed_subscription(sub, SLACK_FAILURE_REASON, None, delivery_id, [self.user.email])
            send_notification_for_failed_subscription(sub, SLACK_FAILURE_REASON, None, uuid.uuid4(), [self.user.email])

        keys = [c.kwargs["campaign_key"] for c in email_cls.call_args_list]
        assert keys[0] == keys[1] == f"subscription-failed-notification-{delivery_id}"
        assert keys[2] != keys[0]
