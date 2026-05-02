from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.slack import _configured_support_channels, handle_support_message


class TestConfiguredSupportChannels(BaseTest):
    @parameterized.expand(
        [
            ("empty_settings", {}, set()),
            ("legacy_only", {"slack_channel_id": "C1"}, {"C1"}),
            ("new_only", {"slack_channel_ids": ["C1", "C2"]}, {"C1", "C2"}),
            ("both_overlapping", {"slack_channel_id": "C1", "slack_channel_ids": ["C1", "C2"]}, {"C1", "C2"}),
            ("both_disjoint", {"slack_channel_id": "C3", "slack_channel_ids": ["C1", "C2"]}, {"C1", "C2", "C3"}),
            ("empty_list_with_legacy", {"slack_channel_id": "C1", "slack_channel_ids": []}, {"C1"}),
            ("none_list", {"slack_channel_ids": None}, set()),
        ],
    )
    def test_configured_support_channels(self, _name, settings, expected):
        assert _configured_support_channels(settings) == expected


class TestSlackMultiChannel(BaseTest):
    def _make_event(
        self, channel: str, text: str = "Hello", ts: str = "1700000000.000100", thread_ts: str | None = None
    ):
        event: dict = {
            "type": "message",
            "channel": channel,
            "ts": ts,
            "user": "U123",
            "text": text,
        }
        if thread_ts is not None:
            event["thread_ts"] = thread_ts
        return event

    @parameterized.expand(
        [
            ("first_configured_creates", "C_ALPHA", True),
            ("second_configured_creates", "C_BETA", True),
            ("unknown_channel_ignored", "C_UNKNOWN", False),
        ],
    )
    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_top_level_message_routing(self, _name, channel, expect_create, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_ids": ["C_ALPHA", "C_BETA"],
        }
        self.team.save()

        handle_support_message(self._make_event(channel), self.team, "T1")

        if expect_create:
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["slack_channel_id"] == channel
            assert mock_create.call_args.kwargs["channel_detail"] == ChannelDetail.SLACK_CHANNEL_MESSAGE
        else:
            mock_create.assert_not_called()

    @parameterized.expand(
        [
            ("configured_channel_accepted", "C_BETA", True),
            ("non_configured_channel_ignored", "C_OTHER", False),
        ],
    )
    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_thread_reply_without_ticket_routing(self, _name, channel, expect_create, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_ids": ["C_ALPHA", "C_BETA"],
        }
        self.team.save()

        handle_support_message(
            self._make_event(channel, thread_ts="1700000000.000001", ts="1700000000.000200"),
            self.team,
            "T1",
        )

        if expect_create:
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["is_thread_reply"] is True
        else:
            mock_create.assert_not_called()

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_thread_reply_with_existing_ticket_syncs_regardless_of_config(self, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_ids": ["C_ALPHA"],
        }
        self.team.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id="C_OTHER",
            slack_thread_ts="1700000000.000001",
        )

        handle_support_message(
            self._make_event("C_OTHER", thread_ts="1700000000.000001", ts="1700000000.000200"),
            self.team,
            "T1",
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is True

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_legacy_slack_channel_id_still_works(self, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_id": "C_LEGACY",
        }
        self.team.save()

        handle_support_message(self._make_event("C_LEGACY"), self.team, "T1")

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["channel_detail"] == ChannelDetail.SLACK_CHANNEL_MESSAGE

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_legacy_and_new_union(self, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
            "slack_channel_id": "C_LEGACY",
            "slack_channel_ids": ["C_NEW"],
        }
        self.team.save()

        handle_support_message(self._make_event("C_LEGACY"), self.team, "T1")
        assert mock_create.call_count == 1

        mock_create.reset_mock()
        handle_support_message(self._make_event("C_NEW", ts="1700000000.000200"), self.team, "T1")
        assert mock_create.call_count == 1

    @patch("products.conversations.backend.slack.create_or_update_slack_ticket")
    def test_no_channels_configured_ignores_all(self, mock_create):
        self.team.conversations_settings = {
            "slack_enabled": True,
        }
        self.team.save()

        handle_support_message(self._make_event("C_ANY"), self.team, "T1")

        mock_create.assert_not_called()
