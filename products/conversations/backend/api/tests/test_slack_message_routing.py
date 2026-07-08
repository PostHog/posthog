from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.slack import (
    handle_member_joined_channel,
    handle_member_left_channel,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
)

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

    @parameterized.expand(
        [
            ("bare_mention", "<@U0BOT001>", None, False),
            ("mention_with_whitespace", "<@U0BOT001>   ", None, False),
            ("mention_with_only_other_mentions", "<@U0BOT001> <@U0USER99>", None, False),
            ("mention_with_text", "<@U0BOT001> help me", None, True),
            ("bare_mention_with_files", "<@U0BOT001>", [{"url_private": "https://x/y.png"}], True),
        ]
    )
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_empty_mention_does_not_create_ticket(self, _name, text, files, should_create, mock_create_or_update):
        handle_support_mention(
            {
                "type": "app_mention",
                "channel": "C_ANY",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": text,
                "files": files,
            },
            self.team,
            "T123",
        )

        assert mock_create_or_update.called is should_create

    @parameterized.expand(
        [
            # No ticket yet: seed from the thread's parent message and backfill replies.
            (
                "seeds_from_parent",
                False,
                [{"user": "U_OP", "text": "Initial message that started the thread"}],
                True,
                "U_OP",
                "Initial message that started the thread",
                False,
            ),
            # Ticket already tracked: just append the mention as a reply, no parent fetch.
            (
                "existing_ticket_adds_reply",
                True,
                None,
                False,
                "U_MENTIONER",
                "<@U_BOT> please help here",
                True,
            ),
            # Parent unavailable (deleted / API hiccup): fall back to the mention itself.
            (
                "parent_unavailable_falls_back",
                False,
                [],
                False,
                "U_MENTIONER",
                "<@U_BOT> please help here",
                False,
            ),
        ]
    )
    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_thread_reply_mention(
        self,
        _name,
        ticket_exists,
        history_messages,
        expect_backfill,
        expected_user,
        expected_text,
        expected_is_thread_reply,
        mock_create_or_update,
        mock_get_client,
        mock_backfill,
    ):
        if ticket_exists:
            Ticket.objects.create_with_number(
                team=self.team,
                channel_source=Channel.SLACK,
                widget_session_id="",
                distinct_id="",
                slack_channel_id="C_ANY",
                slack_thread_ts="1700000000.000100",
            )
        else:
            mock_get_client.return_value.conversations_history.return_value = {"messages": history_messages}
            mock_create_or_update.return_value = object()

        handle_support_mention(
            {
                "type": "app_mention",
                "channel": "C_ANY",
                "thread_ts": "1700000000.000100",
                "ts": "1700000000.000200",
                "user": "U_MENTIONER",
                "text": "<@U_BOT> please help here",
            },
            self.team,
            "T123",
        )

        if ticket_exists:
            mock_get_client.return_value.conversations_history.assert_not_called()
        else:
            mock_get_client.return_value.conversations_history.assert_called_once()

        assert mock_backfill.call_count == (1 if expect_backfill else 0)
        mock_create_or_update.assert_called_once()
        kwargs = mock_create_or_update.call_args.kwargs
        assert kwargs["slack_user_id"] == expected_user
        assert kwargs["text"] == expected_text
        assert kwargs["thread_ts"] == "1700000000.000100"
        assert kwargs["is_thread_reply"] is expected_is_thread_reply
        assert kwargs["channel_detail"] == ChannelDetail.SLACK_BOT_MENTION

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

    @parameterized.expand(
        [
            ("channel_join",),
            ("channel_leave",),
            ("channel_topic",),
            ("channel_purpose",),
            ("pinned_item",),
            ("message_changed",),
            ("message_deleted",),
            # An unrecognized subtype must be treated as noise, not silently ticketed —
            # this is the whole point of using an allowlist over a blocklist.
            ("some_future_subtype",),
        ]
    )
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_system_message_subtype_does_not_create_ticket(self, subtype, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "subtype": subtype,
                "channel": "C_CONFIG",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "<@U123> has joined the channel",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()

    @parameterized.expand(
        [
            ("file_share",),
            ("me_message",),
            ("thread_broadcast",),
        ]
    )
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_content_bearing_subtype_creates_ticket(self, subtype, mock_create_or_update):
        handle_support_message(
            {
                "type": "message",
                "subtype": subtype,
                "channel": "C_CONFIG",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "I need help with something",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_called_once()

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


class TestSlackMemberAlerts(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()  # bot user id is cached per team — keep tests isolated
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_notify_on_join": True,
            "slack_notify_on_leave": True,
            "slack_alert_channel_id": "C_ALERTS",
        }
        self.team.save()

    @parameterized.expand(
        [
            ("join", handle_member_joined_channel, "joined"),
            ("leave", handle_member_left_channel, "left"),
        ]
    )
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_posts_alert(self, _name, handler, verb, mock_get_client, _mock_bot_id):
        handler(
            {"user": "U123", "channel": "C_SUPPORT"},
            self.team,
            "T123",
        )

        mock_get_client.return_value.chat_postMessage.assert_called_once()
        kwargs = mock_get_client.return_value.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C_ALERTS"
        assert kwargs["text"] == f"<@U123> {verb} <#C_SUPPORT>"

    @parameterized.expand(
        [
            ("join", handle_member_joined_channel, "slack_notify_on_join"),
            ("leave", handle_member_left_channel, "slack_notify_on_leave"),
        ]
    )
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_no_op_when_toggle_off(self, _name, handler, toggle_key, mock_get_client, _mock_bot_id):
        self.team.conversations_settings[toggle_key] = False
        self.team.save()

        handler({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_no_alert_without_alert_channel(self, mock_get_client, _mock_bot_id):
        self.team.conversations_settings["slack_alert_channel_id"] = None
        self.team.save()

        handle_member_joined_channel({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_skips_own_bot(self, mock_get_client, _mock_bot_id):
        handle_member_joined_channel({"user": "U_OWN_BOT", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_skips_malformed_ids(self, mock_get_client, _mock_bot_id):
        handle_member_joined_channel({"user": "not-a-user", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.get_bot_user_id", return_value=None)
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_skips_when_bot_id_unresolved(self, mock_get_client, _mock_bot_id):
        handle_member_joined_channel({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_skips_org_member(self, mock_get_client, _mock_bot_id, mock_resolve_user):
        mock_resolve_user.return_value = {"name": "Teammate", "email": self.user.email, "avatar": None}

        handle_member_joined_channel({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_member_event_posts_for_external_user(self, mock_get_client, _mock_bot_id, mock_resolve_user):
        mock_resolve_user.return_value = {"name": "External", "email": "external@example.com", "avatar": None}

        handle_member_joined_channel({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_get_client.return_value.chat_postMessage.assert_called_once()
        kwargs = mock_get_client.return_value.chat_postMessage.call_args.kwargs
        assert kwargs["text"] == "<@U123> joined <#C_SUPPORT>"

    @parameterized.expand(
        [
            ("unconfigured_channel", [], False),
            ("configured_channel", ["C_SUPPORT"], True),
        ]
    )
    @patch(f"{MODULE}.report_team_action")
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_bot_join_fires_posthog_event(
        self, _name, channel_ids, expected_is_configured, mock_get_client, _mock_bot_id, mock_report
    ):
        self.team.conversations_settings["slack_channel_ids"] = channel_ids
        self.team.save()

        handle_member_joined_channel({"user": "U_OWN_BOT", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_report.assert_called_once_with(
            self.team,
            "support slack bot joined channel",
            {"slack_team_id": "T123", "slack_channel_id": "C_SUPPORT", "is_configured_channel": expected_is_configured},
        )
        # It's analytics only — no Slack alert for the bot's own join.
        mock_get_client.return_value.chat_postMessage.assert_not_called()

    @patch(f"{MODULE}.report_team_action")
    @patch(f"{MODULE}.get_bot_user_id", return_value="U_OWN_BOT")
    @patch(f"{MODULE}.get_slack_client")
    def test_non_bot_join_does_not_fire_posthog_event(self, _mock_get_client, _mock_bot_id, mock_report):
        handle_member_joined_channel({"user": "U123", "channel": "C_SUPPORT"}, self.team, "T123")

        mock_report.assert_not_called()
