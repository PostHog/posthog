from posthog.test.base import BaseTest
from unittest.mock import patch

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.slack import handle_support_message


class TestSlackMessageRouting(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_id": "C_CONFIG",
        }
        self.team.save()

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_thread_reply_in_non_configured_channel_syncs_when_ticket_exists(self, mock_create_or_update):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id="C_OTHER",
            slack_thread_ts="1700000000.000100",
        )

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "thread_ts": "1700000000.000100",
                "ts": "1700000000.000200",
                "user": "U123",
                "text": "Reply in thread",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["is_thread_reply"] is True

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_thread_reply_in_non_configured_channel_is_ignored_without_existing_ticket(self, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "thread_ts": "1700000000.000100",
                "ts": "1700000000.000200",
                "user": "U123",
                "text": "Reply in unknown thread",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()
