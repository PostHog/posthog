from posthog.test.base import BaseTest
from unittest.mock import patch

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail
from products.conversations.backend.teams import handle_teams_mention, handle_teams_message


def _make_activity(
    *,
    channel_id: str = "19:ch@thread.tacv2",
    conversation_id: str = "19:conv@thread.tacv2",
    text: str = "Hello",
    reply_to_id: str | None = None,
    from_role: str = "user",
    from_aad_id: str = "aad-user-1",
    service_url: str = "https://smba.trafficmanager.net/teams/",
    bot_mention: bool = False,
) -> dict:
    activity: dict = {
        "type": "message",
        "id": "msg-123",
        "text": text,
        "serviceUrl": service_url,
        "from": {"id": "29:user", "aadObjectId": from_aad_id, "role": from_role},
        "conversation": {"id": conversation_id},
        "channelData": {
            "channel": {"id": channel_id},
            "tenant": {"id": "tenant-abc"},
        },
    }
    if reply_to_id:
        activity["replyToId"] = reply_to_id
    if bot_mention:
        activity["entities"] = [{"type": "mention", "mentioned": {"id": "28:bot", "name": "SupportHog", "role": "bot"}}]
    return activity


class TestTeamsMessageRouting(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channel_id": "19:configured@thread.tacv2",
        }
        self.team.save()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_top_level_message_in_configured_channel_creates_ticket(self, _mock_user, mock_create):
        handle_teams_message(
            _make_activity(channel_id="19:configured@thread.tacv2"),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["is_thread_reply"] is False
        assert kwargs["channel_detail"] == ChannelDetail.TEAMS_CHANNEL_MESSAGE

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_top_level_message_in_other_channel_ignored(self, mock_create):
        handle_teams_message(
            _make_activity(channel_id="19:other@thread.tacv2"),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_thread_reply_with_existing_ticket_syncs(self, _mock_user, mock_create):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.TEAMS,
            widget_session_id="",
            distinct_id="",
            teams_channel_id="19:other@thread.tacv2",
            teams_conversation_id="19:conv@thread.tacv2",
        )

        handle_teams_message(
            _make_activity(
                channel_id="19:other@thread.tacv2",
                conversation_id="19:conv@thread.tacv2",
                reply_to_id="parent-msg",
            ),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is True

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_thread_reply_without_ticket_in_non_configured_channel_ignored(self, mock_create):
        handle_teams_message(
            _make_activity(
                channel_id="19:random@thread.tacv2",
                reply_to_id="parent-msg",
            ),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_bot_message_skipped(self, mock_create):
        handle_teams_message(
            _make_activity(channel_id="19:configured@thread.tacv2", from_role="bot"),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_empty_channel_id_skipped(self, mock_create):
        handle_teams_message(
            _make_activity(channel_id=""),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()


class TestTeamsMentionRouting(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_mention_creates_new_ticket(self, _mock_user, mock_create):
        handle_teams_mention(
            _make_activity(bot_mention=True, channel_id="19:any@thread.tacv2"),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["is_thread_reply"] is False
        assert kwargs["channel_detail"] == ChannelDetail.TEAMS_BOT_MENTION

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    def test_mention_with_existing_ticket_adds_reply(self, _mock_user, mock_create):
        Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.TEAMS,
            widget_session_id="",
            distinct_id="",
            teams_channel_id="19:ch@thread.tacv2",
            teams_conversation_id="19:conv@thread.tacv2",
        )

        handle_teams_mention(
            _make_activity(bot_mention=True),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["is_thread_reply"] is True

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_mention_when_teams_disabled_ignored(self, mock_create):
        self.team.conversations_settings = {"teams_enabled": False}
        self.team.save()

        handle_teams_mention(
            _make_activity(bot_mention=True),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()

    @patch("products.conversations.backend.teams.create_or_update_teams_ticket")
    def test_mention_with_empty_channel_id_ignored(self, mock_create):
        handle_teams_mention(
            _make_activity(bot_mention=True, channel_id=""),
            self.team,
            "tenant-abc",
        )

        mock_create.assert_not_called()
