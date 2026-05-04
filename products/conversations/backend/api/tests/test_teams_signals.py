import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel


def immediate_on_commit(func):
    func()


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestTeamsReplySignal(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"teams_enabled": True}
        self.team.save()
        self.teams_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="teams-user-1",
            channel_source=Channel.TEAMS,
            teams_channel_id="19:ch@thread.tacv2",
            teams_conversation_id="19:conv@thread.tacv2",
            teams_service_url="https://smba.trafficmanager.net/teams/",
            teams_tenant_id="tenant-abc",
        )

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_team_message_enqueues_teams_reply(self, mock_delay, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Support reply",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_called_once()
        call_kwargs = mock_delay.call_args[1]
        assert call_kwargs["teams_conversation_id"] == "19:conv@thread.tacv2"
        assert call_kwargs["teams_service_url"] == "https://smba.trafficmanager.net/teams/"

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_private_message_does_not_enqueue_teams_reply(self, mock_delay, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Private note",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": True},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_customer_message_does_not_enqueue_teams_reply(self, mock_delay, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Customer message",
            item_context={"author_type": "customer", "is_private": False},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_from_teams_message_does_not_echo(self, mock_delay, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Message from Teams",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False, "from_teams": True},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_widget_ticket_does_not_enqueue_teams_reply(self, mock_delay, mock_on_commit):
        widget_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="widget-user-1",
            channel_source="widget",
        )

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(widget_ticket.id),
            content="Reply to widget ticket",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_teams_disabled_does_not_enqueue(self, mock_delay, mock_on_commit):
        self.team.conversations_settings = {"teams_enabled": False}
        self.team.save()

        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Reply",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_teams.delay")
    def test_no_created_by_does_not_enqueue(self, mock_delay, mock_on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.teams_ticket.id),
            content="Anonymous message",
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_not_called()
