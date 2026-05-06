from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.subscription import Subscription

from ee.tasks.subscriptions.auto_disable import (
    SLACK_DISCONNECTED_DISABLE_REASON,
    disable_invalid_subscription,
    send_notifications_for_disabled_subscription,
    validate_re_enable,
)


class TestValidateReEnable:
    """Direct unit tests for the shared re-enable validation helper.

    Mirrors the alert pattern's validate_alert_config tests — one source of truth
    for which target configurations the API rejects up-front.
    """

    @parameterized.expand(
        [
            # (label, target_type, integration_id, expected_None_or_substring)
            ("none_target_passes", None, None, None),
            ("email_no_integration_passes", "email", None, None),
            ("email_with_integration_passes", "email", 42, None),
            ("slack_with_integration_passes", "slack", 42, None),
            ("slack_no_integration_rejected", "slack", None, "no integration configured"),
            ("webhook_no_integration_rejected", "webhook", None, "this delivery channel is not currently supported"),
            ("webhook_with_integration_rejected", "webhook", 42, "this delivery channel is not currently supported"),
        ]
    )
    def test_validate_re_enable(self, _label, target_type, integration_id, expected):
        result = validate_re_enable(target_type, integration_id)
        if expected is None:
            assert result is None
        else:
            assert result is not None
            assert expected in result


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
            disable_invalid_subscription(sub, SLACK_DISCONNECTED_DISABLE_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_called_once_with(sub, SLACK_DISCONNECTED_DISABLE_REASON.description, [self.user.email])

    def test_compare_and_swap_no_op_when_already_disabled(self):
        # Simulates a cross-workflow race: by the time this caller reaches the UPDATE,
        # another caller has already flipped enabled→False. We must NOT re-fire the
        # disabled-notification email (UUID4 campaign keys defeat MessagingRecord dedup).
        sub = self._make_subscription(enabled=False)

        with patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription") as send_mock:
            disable_invalid_subscription(sub, SLACK_DISCONNECTED_DISABLE_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_not_called()

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
            disable_invalid_subscription(sub, SLACK_DISCONNECTED_DISABLE_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_not_called()

    def test_send_notifications_uses_unique_campaign_key_per_call(self):
        sub = self._make_subscription()

        with patch("ee.tasks.subscriptions.auto_disable.EmailMessage") as email_cls:
            send_notifications_for_disabled_subscription(
                sub, SLACK_DISCONNECTED_DISABLE_REASON.description, [self.user.email]
            )
            send_notifications_for_disabled_subscription(
                sub, SLACK_DISCONNECTED_DISABLE_REASON.description, [self.user.email]
            )

        first_key = email_cls.call_args_list[0].kwargs["campaign_key"]
        second_key = email_cls.call_args_list[1].kwargs["campaign_key"]
        # UUID4 suffix makes each call unique regardless of timing — no flakiness
        # if two calls land in the same millisecond.
        assert first_key != second_key
        prefix = f"subscription-disabled-notification-{sub.id}-"
        assert first_key.startswith(prefix)
        assert second_key.startswith(prefix)

    def test_disable_persists_when_email_send_fails(self):
        """Disabling is the durable side effect; email is best-effort.

        If the email send raises (SMTP outage, ImproperlyConfigured on self-hosted,
        Customer.io 5xx) the subscription must still end up disabled and the caller
        must not see an exception — the SLO outcome stays `success`.
        """
        sub = self._make_subscription()

        with (
            patch(
                "ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription",
                side_effect=RuntimeError("smtp down"),
            ) as send_mock,
            patch("ee.tasks.subscriptions.auto_disable.capture_exception") as capture_mock,
        ):
            disable_invalid_subscription(sub, SLACK_DISCONNECTED_DISABLE_REASON)

        sub.refresh_from_db()
        assert sub.enabled is False
        send_mock.assert_called_once()
        capture_mock.assert_called_once()
