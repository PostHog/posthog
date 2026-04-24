from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from products.conversations.backend.models import TeamConversationsTeamsConfig, Ticket
from products.conversations.backend.tasks import post_reply_to_teams, process_teams_event


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
        activity["entities"] = [{"type": "mention", "mentioned": {"id": "28:bot-app-id", "name": "Bot", "role": "bot"}}]
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

    @parameterized.expand(
        [
            # (name, tenant_id, activity_kwargs, disable_teams, expected_tickets, expected_channel_detail)
            ("creates_ticket", "tenant-abc", {}, False, 1, None),
            ("unknown_tenant_returns_early", "unknown", {"tenant_id": "unknown"}, False, 0, None),
            ("teams_disabled_returns_early", "tenant-abc", {}, True, 0, None),
            (
                "bot_mention_dispatches_to_mention_handler",
                "tenant-abc",
                {"bot_mention": True, "channel_id": "19:any@thread.tacv2"},
                False,
                1,
                "teams_bot_mention",
            ),
        ]
    )
    @patch("products.conversations.backend.teams.get_bot_from_id", return_value="28:bot-app-id")
    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    @patch("products.conversations.backend.teams._send_confirmation_card")
    def test_process_event(
        self,
        _name: str,
        tenant_id: str,
        activity_kwargs: dict,
        disable_teams: bool,
        expected_tickets: int,
        expected_channel_detail: str | None,
        _mock_card: MagicMock,
        _mock_user: MagicMock,
        _mock_bot_id: MagicMock,
    ):
        if disable_teams:
            self.team.conversations_settings = {"teams_enabled": False}
            self.team.save()

        process_teams_event(
            activity=_make_activity(**activity_kwargs),
            tenant_id=tenant_id,
            activity_id=f"evt-{_name}",
        )

        tickets = Ticket.objects.filter(team=self.team, channel_source="teams")
        assert tickets.count() == expected_tickets
        if expected_tickets and expected_channel_detail is not None:
            ticket = tickets.first()
            assert ticket is not None
            assert ticket.channel_detail == expected_channel_detail

    @patch("products.conversations.backend.teams.resolve_teams_user", return_value={"name": "U", "email": None})
    @patch("products.conversations.backend.teams._send_confirmation_card")
    def test_duplicate_event_skipped(self, _mock_card, _mock_user):
        process_teams_event(activity=_make_activity(), tenant_id="tenant-abc", activity_id="evt-dup")
        count_before = Ticket.objects.filter(team=self.team, channel_source="teams").count()

        process_teams_event(activity=_make_activity(), tenant_id="tenant-abc", activity_id="evt-dup")

        assert Ticket.objects.filter(team=self.team, channel_source="teams").count() == count_before


class TestPostReplyToTeams(BaseTest):
    @parameterized.expand(
        [
            # (name, team_id_attr, status_code, token_side_effect, expected_post, expected_raises, expected_bearer)
            ("successful_reply", "team_id", 201, None, True, False, "Bearer bot-tok"),
            ("failed_reply_retries", "team_id", 500, None, True, True, "Bearer bot-tok"),
            ("no_bot_token_does_not_retry", "team_id", None, ValueError("not configured"), False, False, None),
            ("nonexistent_team_returns_early", "missing_team_id", 201, None, False, False, None),
        ]
    )
    @patch("products.conversations.backend.tasks.get_bot_from_id", return_value="28:app-id")
    @patch("products.conversations.backend.tasks.get_bot_framework_token")
    @patch("products.conversations.backend.tasks.requests.post")
    def test_post_reply_to_teams(
        self,
        _name: str,
        team_id_attr: str,
        status_code: int | None,
        token_side_effect: Exception | None,
        expected_post: bool,
        expected_raises: bool,
        expected_bearer: str | None,
        mock_post: MagicMock,
        mock_token: MagicMock,
        _mock_from_id: MagicMock,
    ):
        if token_side_effect is not None:
            mock_token.side_effect = token_side_effect
        else:
            mock_token.return_value = "bot-tok"

        if status_code is not None:
            resp = MagicMock()
            resp.status_code = status_code
            resp.text = "err" if status_code >= 400 else ""
            mock_post.return_value = resp

        team_id = self.team.id if team_id_attr == "team_id" else 999999
        kwargs: dict[str, Any] = {
            "ticket_id": "ticket-1",
            "team_id": team_id,
            "content": "Reply text",
            "rich_content": None,
            "author_name": "Agent Smith",
            "teams_service_url": "https://smba.trafficmanager.net/teams/",
            "teams_conversation_id": "19:conv@thread.tacv2",
        }

        if expected_raises:
            with self.assertRaises(Exception):
                post_reply_to_teams(**kwargs)
        else:
            post_reply_to_teams(**kwargs)

        if expected_post:
            mock_post.assert_called_once()
            if expected_bearer:
                assert expected_bearer in mock_post.call_args.kwargs["headers"]["Authorization"]
        else:
            mock_post.assert_not_called()
