import json

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import override_settings

from celery.exceptions import MaxRetriesExceededError
from parameterized import parameterized

from posthog.models.team.extensions import get_or_create_team_extension

from products.conversations.backend.cache import is_nudge_suppressed
from products.conversations.backend.models import TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.slack import (
    TICKET_CONFIRM_ACTION_DISMISS,
    TICKET_CONFIRM_ACTION_OPEN,
    create_ticket_from_confirmation,
    handle_member_joined_channel,
    handle_member_left_channel,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
)
from products.conversations.backend.tasks import process_supporthog_interactivity

MODULE = "products.conversations.backend.slack"
TASKS_MODULE = "products.conversations.backend.tasks"


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

    @patch("products.conversations.backend.slack.get_slack_client")
    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_top_level_message_passes_channel_detail(self, mock_create_or_update, mock_get_client):
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
        # Confirm-before-ticket is off by default: the ticket is created directly,
        # never a nudge prompt.
        mock_get_client.return_value.chat_postMessage.assert_not_called()

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

    @patch(f"{MODULE}.resolve_posthog_user_for_slack")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_internal_user_can_open_ticket_via_mention(self, mock_create_or_update, mock_resolve_user):
        mock_resolve_user.return_value = self.user

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

    @patch(f"{MODULE}.resolve_posthog_user_for_slack")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_internal_user_can_open_ticket_via_emoji(self, mock_create_or_update, mock_get_client, mock_resolve_user):
        mock_resolve_user.return_value = self.user
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


class TestSlackNudge(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()  # nudge suppression + bot user id are cached per team
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_id": "C_CONFIG",
        }
        self.team.save()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_message_in_other_channel_posts_prompt_by_default(self, mock_create_or_update, mock_get_client):
        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        mock_create_or_update.assert_not_called()
        mock_get_client.return_value.chat_postMessage.assert_called_once()
        kwargs = mock_get_client.return_value.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C_OTHER"
        assert kwargs["thread_ts"] == "1700000000.000100"
        # Mentions the author so they actually get notified (a plain ephemeral is silent).
        assert "<@U123>" in kwargs["text"]
        action_ids = {
            element["action_id"]
            for block in kwargs["blocks"]
            if block["type"] == "actions"
            for element in block["elements"]
        }
        assert action_ids == {TICKET_CONFIRM_ACTION_OPEN, TICKET_CONFIRM_ACTION_DISMISS}
        # The prompt also points at the other ways to open a ticket.
        context_texts = [
            element["text"] for block in kwargs["blocks"] if block["type"] == "context" for element in block["elements"]
        ]
        assert any("react to your original message" in text for text in context_texts)

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_malicious_ticket_emoji_falls_back_in_prompt(self, _mock_create_or_update, mock_get_client):
        # The emoji setting is team-editable and interpolated into mrkdwn — a value
        # carrying mentions must not reach Slack.
        self.team.conversations_settings = {
            **self.team.conversations_settings,
            "slack_ticket_emoji": "ticket: <!channel> :ticket",
        }
        self.team.save()

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        kwargs = mock_get_client.return_value.chat_postMessage.call_args.kwargs
        rendered = json.dumps(kwargs["blocks"])
        assert "<!channel>" not in rendered
        assert ":ticket:" in rendered

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_no_prompt_when_nudge_disabled(self, mock_create_or_update, mock_get_client):
        self.team.conversations_settings = {**self.team.conversations_settings, "slack_nudge_enabled": False}
        self.team.save()

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_thread_reply_in_other_channel_still_syncs_without_prompt(self, mock_create_or_update, mock_get_client):
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

        mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_called_once()
        assert mock_create_or_update.call_args.kwargs["is_thread_reply"] is True

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_bot_mention_in_top_level_message_skips_prompt(self, mock_create_or_update, mock_get_client):
        mock_get_client.return_value.auth_test.return_value = {"user_id": "UBOT123"}

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "<@UBOT123> can you please take a look",
            },
            self.team,
            "T123",
        )

        # The app_mention event opens the ticket; no nudge prompt and no auto-create here.
        mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_trivial_message_skips_prompt(self, mock_create_or_update, mock_get_client):
        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "thanks :+1:",
            },
            self.team,
            "T123",
        )

        mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.resolve_posthog_user_for_slack")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_internal_user_skips_prompt(self, mock_create_or_update, mock_get_client, mock_resolve_user):
        mock_resolve_user.return_value = self.user  # author resolves to an org member

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_does_not_renudge_same_user_within_cooldown(self, mock_create_or_update, mock_get_client):
        event = {
            "type": "message",
            "channel": "C_OTHER",
            "user": "U123",
            "text": "my data export keeps failing",
        }
        handle_support_message({**event, "ts": "1700000000.000100"}, self.team, "T123")
        handle_support_message({**event, "ts": "1700000000.000200"}, self.team, "T123")

        # First message nudges and sets a cooldown; the second is suppressed.
        mock_get_client.return_value.chat_postMessage.assert_called_once()

    @parameterized.expand(
        [
            ("classifier_says_yes", "yes", True),
            ("classifier_says_yes_with_punctuation", "Yes.", True),
            ("classifier_says_no", "no", False),
            ("classifier_call_fails_degrades_to_heuristics", None, True),
        ]
    )
    @override_settings(TEST=False, LLM_GATEWAY_URL="http://gateway.local", LLM_GATEWAY_API_KEY="test-key")
    @patch(f"{MODULE}.posthoganalytics.feature_enabled", return_value=True)
    @patch(f"{MODULE}.get_llm_client")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_llm_gates_nudge_when_ai_processing_approved(
        self,
        _name,
        llm_answer,
        expect_prompt,
        mock_create_or_update,
        mock_get_client,
        mock_get_llm_client,
        _mock_flag_enabled,
    ):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        if llm_answer is None:
            # A gateway failure must be swallowed (no Celery retry storm) and fall back to
            # the heuristics-only nudge instead of silently disabling the feature.
            mock_get_llm_client.return_value.chat.completions.create.side_effect = RuntimeError("gateway down")
        else:
            completion = Mock()
            completion.choices = [Mock(message=Mock(content=llm_answer))]
            mock_get_llm_client.return_value.chat.completions.create.return_value = completion

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        if expect_prompt:
            mock_get_client.return_value.chat_postMessage.assert_called_once()
        else:
            mock_get_client.return_value.chat_postMessage.assert_not_called()
        mock_create_or_update.assert_not_called()

    @parameterized.expand(
        [
            ("ai_processing_off", False, True),
            ("rollout_flag_off", True, False),
        ]
    )
    @override_settings(TEST=False, LLM_GATEWAY_URL="http://gateway.local", LLM_GATEWAY_API_KEY="test-key")
    @patch(f"{MODULE}.posthoganalytics.feature_enabled")
    @patch(f"{MODULE}.get_llm_client")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_nudge_never_calls_llm_when_gated_off(
        self,
        _name,
        ai_approved,
        flag_enabled,
        mock_create_or_update,
        mock_get_client,
        mock_get_llm_client,
        mock_flag_enabled,
    ):
        # Opted-out orgs must not have customer messages sent to the LLM gateway, and the
        # rollout flag must be able to hold the classifier off; both keep the heuristics-only
        # nudge working.
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()
        mock_flag_enabled.return_value = flag_enabled

        handle_support_message(
            {
                "type": "message",
                "channel": "C_OTHER",
                "ts": "1700000000.000100",
                "user": "U123",
                "text": "my data export keeps failing",
            },
            self.team,
            "T123",
        )

        mock_get_llm_client.assert_not_called()
        mock_get_client.return_value.chat_postMessage.assert_called_once()
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}._backfill_thread_replies")
    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_create_ticket_from_confirmation_seeds_from_message(
        self, mock_create_or_update, mock_get_client, mock_backfill
    ):
        mock_get_client.return_value.conversations_history.return_value = {
            "messages": [{"user": "U_OP", "text": "Original message", "ts": "1700000000.000100"}]
        }
        mock_create_or_update.return_value = object()

        create_ticket_from_confirmation(
            team=self.team,
            slack_team_id="T123",
            slack_channel_id="C_OTHER",
            message_ts="1700000000.000100",
        )

        mock_create_or_update.assert_called_once()
        kwargs = mock_create_or_update.call_args.kwargs
        assert kwargs["slack_user_id"] == "U_OP"
        assert kwargs["text"] == "Original message"
        assert kwargs["thread_ts"] == "1700000000.000100"
        assert kwargs["is_thread_reply"] is False
        assert kwargs["channel_detail"] == ChannelDetail.SLACK_CHANNEL_MESSAGE
        mock_backfill.assert_called_once()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_create_ticket_from_confirmation_rejects_wrong_message(self, mock_create_or_update, mock_get_client):
        # `latest` is an upper bound: if the source message was deleted, Slack returns the
        # previous channel message instead. That must not seed a ticket.
        mock_get_client.return_value.conversations_history.return_value = {
            "messages": [{"user": "U_SOMEONE_ELSE", "text": "Unrelated earlier message", "ts": "1699999999.000001"}]
        }

        result = create_ticket_from_confirmation(
            team=self.team,
            slack_team_id="T123",
            slack_channel_id="C_OTHER",
            message_ts="1700000000.000100",
        )

        assert result is None
        mock_create_or_update.assert_not_called()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.create_or_update_slack_ticket")
    def test_create_ticket_from_confirmation_is_idempotent(self, mock_create_or_update, mock_get_client):
        existing = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id="C_OTHER",
            slack_thread_ts="1700000000.000100",
        )

        result = create_ticket_from_confirmation(
            team=self.team,
            slack_team_id="T123",
            slack_channel_id="C_OTHER",
            message_ts="1700000000.000100",
        )

        mock_get_client.assert_not_called()
        mock_create_or_update.assert_not_called()
        assert result == existing


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


class TestSupporthogInteractivity(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        config = get_or_create_team_extension(self.team, TeamConversationsSlackConfig)
        config.slack_team_id = "T123"
        config.slack_bot_token = "xoxb-test"
        config.save(update_fields=["slack_team_id", "slack_bot_token"])

    def _payload(self, action_id: str, value: dict) -> dict:
        return {
            "type": "block_actions",
            "team": {"id": "T123"},
            "user": {"id": "U_CLICKER"},
            "channel": {"id": "C_CONFIG"},
            "message": {"ts": "1700000000.000999"},
            "actions": [{"action_id": action_id, "value": json.dumps(value)}],
        }

    @patch(f"{TASKS_MODULE}.get_slack_client")
    def test_disabled_team_is_noop(self, mock_get_client):
        self.team.conversations_settings = {"slack_enabled": False}
        self.team.save()

        process_supporthog_interactivity(
            self._payload(TICKET_CONFIRM_ACTION_OPEN, {"channel": "C_CONFIG", "message_ts": "1700000000.000100"}),
            "T123",
        )

        mock_get_client.assert_not_called()

    @patch(f"{TASKS_MODULE}.get_slack_client")
    def test_dismiss_deletes_prompt_acks_and_suppresses(self, mock_get_client):
        mock_get_client.return_value.auth_test.return_value = {"user_id": "U_BOT"}

        process_supporthog_interactivity(
            self._payload(TICKET_CONFIRM_ACTION_DISMISS, {"channel": "C_CONFIG", "message_ts": "1700000000.000100"}),
            "T123",
        )

        client = mock_get_client.return_value
        client.chat_delete.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        assert is_nudge_suppressed(self.team.pk, "C_CONFIG", "U_CLICKER")

    @parameterized.expand(
        [
            (
                "created",
                {"channel": "C_CONFIG", "message_ts": "1700000000.000100"},
                Mock(ticket_number=42),
                True,
                "ticket #42",
            ),
            (
                "genuine_failure",
                {"channel": "C_CONFIG", "message_ts": "1700000000.000100"},
                None,
                True,
                "couldn't",
            ),
            ("malformed_value", {}, None, False, "couldn't"),
        ]
    )
    @patch(f"{TASKS_MODULE}.get_slack_client")
    @patch(f"{TASKS_MODULE}.create_ticket_from_confirmation")
    def test_open_replaces_prompt_with_confirmation_or_error(
        self, _name, value, create_return, expect_create_called, expected_text, mock_create, mock_get_client
    ):
        mock_create.return_value = create_return

        process_supporthog_interactivity(self._payload(TICKET_CONFIRM_ACTION_OPEN, value), "T123")

        assert mock_create.call_count == (1 if expect_create_called else 0)
        client = mock_get_client.return_value
        client.chat_update.assert_called_once()
        assert expected_text in client.chat_update.call_args.kwargs["text"].lower()

    @patch(f"{TASKS_MODULE}.get_slack_client")
    @patch(f"{TASKS_MODULE}.create_ticket_from_confirmation")
    def test_open_shows_error_when_retries_exhausted(self, mock_create, mock_get_client):
        # A persistent failure retries and eventually exhausts — the prompt must still be
        # replaced with the error state, not left with live buttons forever.
        mock_create.side_effect = RuntimeError("boom")

        with patch.object(process_supporthog_interactivity, "retry", side_effect=MaxRetriesExceededError()):
            process_supporthog_interactivity(
                self._payload(TICKET_CONFIRM_ACTION_OPEN, {"channel": "C_CONFIG", "message_ts": "1700000000.000100"}),
                "T123",
            )

        client = mock_get_client.return_value
        client.chat_update.assert_called_once()
        assert "couldn't" in client.chat_update.call_args.kwargs["text"].lower()
