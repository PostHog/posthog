from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.teams import _configured_support_channel_ids, handle_teams_message


class TestConfiguredSupportChannelIds(BaseTest):
    @parameterized.expand(
        [
            ("empty_settings", {}, set()),
            ("legacy_only", {"teams_channel_id": "19:ch1@thread.tacv2"}, {"19:ch1@thread.tacv2"}),
            (
                "new_only",
                {
                    "teams_channels": [
                        {"team_id": "t1", "channel_id": "19:ch1@thread.tacv2"},
                        {"team_id": "t2", "channel_id": "19:ch2@thread.tacv2"},
                    ]
                },
                {"19:ch1@thread.tacv2", "19:ch2@thread.tacv2"},
            ),
            (
                "both_overlapping",
                {
                    "teams_channel_id": "19:ch1@thread.tacv2",
                    "teams_channels": [
                        {"team_id": "t1", "channel_id": "19:ch1@thread.tacv2"},
                        {"team_id": "t2", "channel_id": "19:ch2@thread.tacv2"},
                    ],
                },
                {"19:ch1@thread.tacv2", "19:ch2@thread.tacv2"},
            ),
            (
                "both_disjoint",
                {
                    "teams_channel_id": "19:ch3@thread.tacv2",
                    "teams_channels": [
                        {"team_id": "t1", "channel_id": "19:ch1@thread.tacv2"},
                        {"team_id": "t2", "channel_id": "19:ch2@thread.tacv2"},
                    ],
                },
                {"19:ch1@thread.tacv2", "19:ch2@thread.tacv2", "19:ch3@thread.tacv2"},
            ),
            (
                "empty_list_with_legacy",
                {"teams_channel_id": "19:ch1@thread.tacv2", "teams_channels": []},
                {"19:ch1@thread.tacv2"},
            ),
            ("none_list", {"teams_channels": None}, set()),
            (
                "malformed_entry_skipped",
                {
                    "teams_channels": [
                        {"team_id": "t1", "channel_id": "19:ch1@thread.tacv2"},
                        {"team_id": "t2"},  # missing channel_id
                        "invalid",  # not a dict
                    ]
                },
                {"19:ch1@thread.tacv2"},
            ),
        ],
    )
    def test_configured_support_channel_ids(self, _name, settings, expected):
        assert _configured_support_channel_ids(settings) == expected


def _make_activity(
    *,
    channel_id: str = "19:ch@thread.tacv2",
    conversation_id: str = "19:conv@thread.tacv2",
    text: str = "Hello",
    reply_to_id: str | None = None,
    service_url: str = "https://smba.trafficmanager.net/teams/",
) -> dict:
    activity_id = "msg-123"
    activity: dict = {
        "type": "message",
        "id": activity_id,
        "text": text,
        "serviceUrl": service_url,
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "role": "user"},
        "conversation": {"id": f"{conversation_id};messageid={activity_id}"},
        "channelData": {
            "channel": {"id": channel_id},
            "tenant": {"id": "tenant-abc"},
        },
    }
    if reply_to_id:
        activity["replyToId"] = reply_to_id
        activity["conversation"]["id"] = f"{conversation_id};messageid={reply_to_id}"
    return activity


class TestTeamsMultiChannel(BaseTest):
    @parameterized.expand(
        [
            ("first_configured_creates", "19:alpha@thread.tacv2", True),
            ("second_configured_creates", "19:beta@thread.tacv2", True),
            ("unknown_channel_ignored", "19:unknown@thread.tacv2", False),
        ],
    )
    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_top_level_message_routing(self, _name, channel, expect_create, _mock_user, mock_create):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t1", "channel_id": "19:alpha@thread.tacv2"},
                {"team_id": "t2", "channel_id": "19:beta@thread.tacv2"},
            ],
        }
        self.team.save()

        handle_teams_message(_make_activity(channel_id=channel), self.team, "tenant-abc")

        if expect_create:
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["channel_detail"] == ChannelDetail.TEAMS_CHANNEL_MESSAGE
        else:
            mock_create.assert_not_called()

    @parameterized.expand(
        [
            ("configured_channel_accepted", "19:beta@thread.tacv2", True),
            ("non_configured_channel_ignored", "19:other@thread.tacv2", False),
        ],
    )
    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_thread_reply_without_ticket_routing(self, _name, channel, expect_create, _mock_user, mock_create):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "t1", "channel_id": "19:alpha@thread.tacv2"},
                {"team_id": "t2", "channel_id": "19:beta@thread.tacv2"},
            ],
        }
        self.team.save()

        handle_teams_message(
            _make_activity(channel_id=channel, reply_to_id="parent-msg"),
            self.team,
            "tenant-abc",
        )

        if expect_create:
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["is_thread_reply"] is True
        else:
            mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_thread_reply_with_existing_ticket_syncs_regardless_of_config(self, _mock_user, mock_create):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [{"team_id": "t1", "channel_id": "19:alpha@thread.tacv2"}],
        }
        self.team.save()

        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.TEAMS,
            widget_session_id="",
            distinct_id="",
            teams_channel_id="19:other@thread.tacv2",
            teams_conversation_id="19:conv@thread.tacv2;messageid=parent-msg",
        )

        handle_teams_message(
            _make_activity(channel_id="19:other@thread.tacv2", reply_to_id="parent-msg"),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is True

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_legacy_teams_channel_id_still_works(self, _mock_user, mock_create):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channel_id": "19:legacy@thread.tacv2",
        }
        self.team.save()

        handle_teams_message(_make_activity(channel_id="19:legacy@thread.tacv2"), self.team, "tenant-abc")

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["channel_detail"] == ChannelDetail.TEAMS_CHANNEL_MESSAGE

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_legacy_and_new_union(self, _mock_user, mock_create):
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channel_id": "19:legacy@thread.tacv2",
            "teams_channels": [{"team_id": "t1", "channel_id": "19:new@thread.tacv2"}],
        }
        self.team.save()

        handle_teams_message(_make_activity(channel_id="19:legacy@thread.tacv2"), self.team, "tenant-abc")
        assert mock_create.call_count == 1

        mock_create.reset_mock()
        handle_teams_message(
            _make_activity(channel_id="19:new@thread.tacv2", conversation_id="19:conv2@thread.tacv2"),
            self.team,
            "tenant-abc",
        )
        assert mock_create.call_count == 1

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_no_channels_configured_ignores_all(self, mock_create):
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()

        handle_teams_message(_make_activity(channel_id="19:any@thread.tacv2"), self.team, "tenant-abc")

        mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_shared_channel_in_multiple_teams_dedupe(self, _mock_user, mock_create):
        """Shared channel configured under two different MS Teams groups should only create one ticket."""
        shared_channel = "19:shared@thread.tacv2"
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channels": [
                {"team_id": "team-a", "channel_id": shared_channel},
                {"team_id": "team-b", "channel_id": shared_channel},
            ],
        }
        self.team.save()

        handle_teams_message(_make_activity(channel_id=shared_channel), self.team, "tenant-abc")

        # Should create exactly one ticket, not two
        mock_create.assert_called_once()
