from posthog.test.base import BaseTest
from unittest.mock import patch

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.slack import handle_support_mention, handle_support_message, handle_support_reaction

MODULE = "products.conversations.backend.slack"


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

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_top_level_message_passes_channel_detail(self, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "channel": "C_CONFIG",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "New support request",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["channel_detail"] == ChannelDetail.SLACK_CHANNEL_MESSAGE
        assert mock_create_or_update.call_args.kwargs["is_thread_reply"] is False

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_bot_mention_passes_channel_detail(self, mock_create_or_update):
        handle_support_mention(
            {
                "type": "app_mention",
                "channel": "C_ANY",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "<@U_BOT> help me",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["channel_detail"] == ChannelDetail.SLACK_BOT_MENTION

    @patch("products.conversations.backend.slack.get_slack_client")
    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_emoji_reaction_passes_channel_detail(self, mock_create_or_update, mock_get_client):
        mock_get_client.return_value.conversations_history.return_value = {
            "messages": [{"user": "U123", "text": "Original message"}]
        }

        handle_support_reaction(
            {
                "type": "reaction_added",
                "reaction": "ticket",
                "item": {"channel": "C_CONFIG", "ts": "1700000000.000100"},
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["channel_detail"] == ChannelDetail.SLACK_EMOJI_REACTION

    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_top_level_bot_message_does_not_create_ticket(self, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "channel": "C_CONFIG",
                "ts": "1700000000.000100",
                "user": "U_BOT",
                "text": "Automated alert",
                "bot_id": "B123",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_top_level_bot_message_subtype_does_not_create_ticket(self, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "subtype": "bot_message",
                "channel": "C_CONFIG",
                "ts": "1700000000.000100",
                "user": "U_BOT",
                "text": "Webhook post",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_other_bot_thread_reply_creates_comment(self, mock_create_or_update, _mock_client, _mock_bot_id):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id="C_CONFIG",
            slack_thread_ts="1700000000.000100",
        )

        handle_support_message(
            {
                "type": "message",
                "channel": "C_CONFIG",
                "thread_ts": "1700000000.000100",
                "ts": "1700000000.000200",
                "user": "U_OTHER_BOT",
                "text": "Bot summary",
                "bot_id": "B_OTHER",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["is_thread_reply"] is True

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_own_bot_thread_reply_is_skipped(self, mock_create_or_update, _mock_client, _mock_bot_id):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id="C_CONFIG",
            slack_thread_ts="1700000000.000100",
        )

        handle_support_message(
            {
                "type": "message",
                "channel": "C_CONFIG",
                "thread_ts": "1700000000.000100",
                "ts": "1700000000.000200",
                "user": "U_OWN_BOT",
                "text": "Ticket #1 created",
                "bot_id": "B_OWN",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()
