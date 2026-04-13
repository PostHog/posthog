from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from products.conversations.backend.models import TeamConversationsTeamsConfig


def _make_activity(
    *,
    channel_id: str = "19:ch@thread.tacv2",
    conversation_id: str = "19:conv@thread.tacv2",
    tenant_id: str = "tenant-abc",
    text: str = "Hello",
    bot_mention: bool = False,
    reply_to_id: str | None = None,
) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "type": "message",
        "id": "act-123",
        "text": text,
        "serviceUrl": "https://smba.trafficmanager.net/teams/",
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "role": "user"},
        "conversation": {"id": conversation_id},
        "channelData": {
            "channel": {"id": channel_id},
            "tenant": {"id": tenant_id},
        },
    }
    if reply_to_id:
        activity["replyToId"] = reply_to_id
    if bot_mention:
        activity["entities"] = [{"type": "mention", "mentioned": {"id": "28:bot", "name": "Bot", "role": "bot"}}]
    return activity


class TestProcessTeamsEvent(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {
            "teams_enabled": True,
            "teams_channel_id": "19:ch@thread.tacv2",
        }
        self.team.save()
        TeamConversationsTeamsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "teams_tenant_id": "tenant-abc",
                "teams_graph_access_token": "graph-tok",
                "teams_graph_refresh_token": "graph-ref",
            },
        )
        cache.clear()

    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    @patch("products.conversations.backend.teams._send_confirmation_card")
    def test_process_event_creates_ticket(self, _mock_card, _mock_user):
        from products.conversations.backend.tasks import process_teams_event

        process_teams_event(
            activity=_make_activity(),
            tenant_id="tenant-abc",
            activity_id="evt-1",
        )

        from products.conversations.backend.models import Ticket

        ticket = Ticket.objects.filter(team=self.team, channel_source="teams").first()
        assert ticket is not None
        assert ticket.teams_channel_id == "19:ch@thread.tacv2"
        assert ticket.teams_tenant_id == "tenant-abc"

    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    @patch("products.conversations.backend.teams._send_confirmation_card")
    def test_duplicate_event_skipped(self, _mock_card, _mock_user):
        from products.conversations.backend.tasks import process_teams_event

        process_teams_event(
            activity=_make_activity(),
            tenant_id="tenant-abc",
            activity_id="evt-dup",
        )

        from products.conversations.backend.models import Ticket

        count_before = Ticket.objects.filter(team=self.team, channel_source="teams").count()

        process_teams_event(
            activity=_make_activity(),
            tenant_id="tenant-abc",
            activity_id="evt-dup",
        )

        count_after = Ticket.objects.filter(team=self.team, channel_source="teams").count()
        assert count_after == count_before

    def test_process_event_unknown_tenant_returns_early(self):
        from products.conversations.backend.tasks import process_teams_event

        # Should not raise
        process_teams_event(
            activity=_make_activity(tenant_id="unknown"),
            tenant_id="unknown",
            activity_id="evt-unknown",
        )

    def test_process_event_teams_disabled_returns_early(self):
        self.team.conversations_settings = {"teams_enabled": False}
        self.team.save()

        from products.conversations.backend.tasks import process_teams_event

        process_teams_event(
            activity=_make_activity(),
            tenant_id="tenant-abc",
            activity_id="evt-disabled",
        )

        from products.conversations.backend.models import Ticket

        assert Ticket.objects.filter(team=self.team, channel_source="teams").count() == 0

    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    @patch("products.conversations.backend.teams._send_confirmation_card")
    def test_bot_mention_dispatches_to_mention_handler(self, _mock_card, _mock_user):
        from products.conversations.backend.tasks import process_teams_event

        process_teams_event(
            activity=_make_activity(bot_mention=True, channel_id="19:any@thread.tacv2"),
            tenant_id="tenant-abc",
            activity_id="evt-mention",
        )

        from products.conversations.backend.models import Ticket

        ticket = Ticket.objects.filter(team=self.team, channel_source="teams").first()
        assert ticket is not None
        assert ticket.channel_detail == "teams_bot_mention"


class TestPostReplyToTeams(BaseTest):
    @patch("products.conversations.backend.support_teams.get_bot_framework_token", return_value="bot-tok")
    @patch("products.conversations.backend.tasks.requests.post")
    def test_successful_reply(self, mock_post, _mock_token):
        from products.conversations.backend.tasks import post_reply_to_teams

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        post_reply_to_teams(
            ticket_id="ticket-1",
            team_id=self.team.id,
            content="Reply text",
            rich_content=None,
            author_name="Agent Smith",
            teams_service_url="https://smba.trafficmanager.net/teams/",
            teams_conversation_id="19:conv@thread.tacv2",
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "Bearer bot-tok" in call_kwargs.kwargs["headers"]["Authorization"]
        payload = call_kwargs.kwargs["json"]
        assert payload["conversation"]["id"] == "19:conv@thread.tacv2"
        assert "Reply text" in payload["text"]

    @patch("products.conversations.backend.support_teams.get_bot_framework_token", return_value="bot-tok")
    @patch("products.conversations.backend.tasks.requests.post")
    def test_failed_reply_retries(self, mock_post, _mock_token):
        from products.conversations.backend.tasks import post_reply_to_teams

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        with self.assertRaises(Exception, msg="Teams reply failed with status 500"):
            post_reply_to_teams(
                ticket_id="ticket-1",
                team_id=self.team.id,
                content="Reply",
                rich_content=None,
                author_name="Agent",
                teams_service_url="https://smba.trafficmanager.net/teams/",
                teams_conversation_id="19:conv@thread.tacv2",
            )

    @patch(
        "products.conversations.backend.support_teams.get_bot_framework_token", side_effect=ValueError("not configured")
    )
    def test_no_bot_token_does_not_retry(self, _mock_token):
        from products.conversations.backend.tasks import post_reply_to_teams

        # Should not raise — just returns silently
        post_reply_to_teams(
            ticket_id="ticket-1",
            team_id=self.team.id,
            content="Reply",
            rich_content=None,
            author_name="Agent",
            teams_service_url="https://smba.trafficmanager.net/teams/",
            teams_conversation_id="19:conv@thread.tacv2",
        )

    @patch("products.conversations.backend.support_teams.get_bot_framework_token", return_value="bot-tok")
    @patch("products.conversations.backend.tasks.requests.post")
    def test_nonexistent_team_returns_early(self, mock_post, _mock_token):
        from products.conversations.backend.tasks import post_reply_to_teams

        post_reply_to_teams(
            ticket_id="ticket-1",
            team_id=999999,
            content="Reply",
            rich_content=None,
            author_name="Agent",
            teams_service_url="https://smba.trafficmanager.net/teams/",
            teams_conversation_id="19:conv@thread.tacv2",
        )

        mock_post.assert_not_called()
