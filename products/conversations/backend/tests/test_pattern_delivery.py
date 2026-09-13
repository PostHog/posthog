from __future__ import annotations

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.annotations.backend.models.annotation import Annotation
from products.conversations.backend.models import TicketPattern
from products.conversations.backend.pattern_delivery import (
    SLACK_POSTED_KEY,
    annotate_confirmation,
    deliver_opened,
    deliver_resolved,
)

DELIVERY = "products.conversations.backend.pattern_delivery"


class TestPatternDelivery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        now = timezone.now()
        self.pattern = TicketPattern.objects.for_team(self.team.id).create(
            team=self.team,
            fingerprint="terms:login",
            topic="login",
            title="Login",
            ticket_count=6,
            requester_count=6,
            peak_ticket_count=6,
            first_ticket_at=now,
            opened_at=now,
            last_seen_at=now,
        )

    @parameterized.expand(
        [
            ("no_role_no_channel", {}, False, False),
            ("role_only", {"pattern_notify_role_id": "11111111-1111-1111-1111-111111111111"}, True, False),
            ("channel_only", {"slack_alert_channel_id": "C123"}, False, True),
        ]
    )
    def test_each_delivery_channel_needs_its_own_setting(self, _name, settings, expect_notify, expect_slack):
        self.team.conversations_settings = settings
        self.team.save()

        with (
            patch(f"{DELIVERY}.create_notification") as notify,
            patch(f"{DELIVERY}.get_support_slack_bot_token", return_value="xoxb-test"),
            patch(f"{DELIVERY}.get_slack_client") as slack,
            patch(f"{DELIVERY}.capture_pattern_detected") as capture,
        ):
            deliver_opened(self.pattern)

        assert notify.called is expect_notify
        assert slack.return_value.chat_postMessage.called is expect_slack
        capture.assert_called_once_with(self.pattern)

    def test_slack_posts_once_across_redelivery(self):
        self.team.conversations_settings = {"slack_alert_channel_id": "C123"}
        self.team.save()

        with (
            patch(f"{DELIVERY}.get_support_slack_bot_token", return_value="xoxb-test"),
            patch(f"{DELIVERY}.get_slack_client") as slack,
            patch(f"{DELIVERY}.capture_pattern_detected"),
        ):
            deliver_opened(self.pattern)
            self.pattern.refresh_from_db()
            deliver_opened(self.pattern)

        assert slack.return_value.chat_postMessage.call_count == 1
        assert self.pattern.evidence[SLACK_POSTED_KEY] is True
        posted_text = slack.return_value.chat_postMessage.call_args.kwargs["text"]
        assert "6 tickets from 6 customers about login" in posted_text

    def test_notification_carries_the_pattern_idempotency_key(self):
        self.team.conversations_settings = {"pattern_notify_role_id": "11111111-1111-1111-1111-111111111111"}
        self.team.save()

        with patch(f"{DELIVERY}.create_notification") as notify, patch(f"{DELIVERY}.capture_pattern_detected"):
            deliver_opened(self.pattern)

        data = notify.call_args.args[0]
        assert data.idempotency_key == f"conversations-pattern:{self.pattern.id}"
        assert data.target_type.value == "role"
        assert data.priority.value == "normal"

    @parameterized.expand([("confirmed",), ("dismissed",), ("auto",)])
    def test_resolution_is_captured_with_its_kind(self, resolution):
        with patch(f"{DELIVERY}.capture_pattern_resolved") as capture:
            deliver_resolved(self.pattern, resolution)

        capture.assert_called_once_with(self.pattern, resolution)

    def test_confirmation_annotates_the_project_at_the_first_ticket(self):
        annotate_confirmation(self.pattern, self.user)

        annotation = Annotation.objects.get(team=self.team)
        assert annotation.scope == Annotation.Scope.PROJECT
        assert annotation.date_marker == self.pattern.first_ticket_at
        assert annotation.created_by == self.user
        assert "Login" in annotation.content
