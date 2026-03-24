from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction

from posthog.models.comment import Comment
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.slack import (
    _backfill_thread_replies,
    create_or_update_slack_ticket,
    resolve_posthog_user_for_slack,
)

MODULE = "products.conversations.backend.slack"

CHANNEL_ID = "C_SUPPORT"
PARENT_TS = "1700000000.000100"
REPLY_TS = "1700000000.000200"
SLACK_TEAM = "T_WORKSPACE"


def _team_member_user_info(email: str) -> dict:
    return {"name": "Team Member", "email": email, "avatar": "https://av/team.png"}


def _customer_user_info() -> dict:
    return {"name": "Customer", "email": "customer@example.com", "avatar": None}


def immediate_on_commit(func):
    func()


class TestResolvePosthogUserForSlack(BaseTest):
    def test_returns_user_when_email_matches_org_member(self):
        result = resolve_posthog_user_for_slack(self.user.email, self.team)
        assert result is not None
        assert result.id == self.user.id

    def test_returns_none_for_non_member_email(self):
        result = resolve_posthog_user_for_slack("stranger@example.com", self.team)
        assert result is None

    def test_returns_none_for_empty_email(self):
        assert resolve_posthog_user_for_slack(None, self.team) is None
        assert resolve_posthog_user_for_slack("", self.team) is None

    def test_scoped_to_team_organization(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org)
        result = resolve_posthog_user_for_slack(self.user.email, other_team)
        assert result is None


class TestCreateOrUpdateSlackTicketTeamMemberDetection(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"slack_enabled": True, "slack_channel_id": CHANNEL_ID}
        self.team.save()

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_new_ticket_from_team_member_sets_support_author_type(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _team_member_user_info(self.user.email)
        mock_client.return_value = MagicMock()

        ticket = create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_TEAM",
            text="I'll create this ticket",
            slack_team_id=SLACK_TEAM,
        )

        assert ticket is not None
        comment = Comment.objects.get(item_id=str(ticket.id))
        assert comment.item_context["author_type"] == "support"
        assert comment.item_context["from_slack"] is True
        assert comment.created_by_id == self.user.id

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_new_ticket_from_team_member_has_zero_unread_team_count(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _team_member_user_info(self.user.email)
        mock_client.return_value = MagicMock()

        ticket = create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_TEAM",
            text="Team member opens ticket",
            slack_team_id=SLACK_TEAM,
        )

        assert ticket is not None
        ticket.refresh_from_db()
        assert ticket.unread_team_count == 0

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_new_ticket_from_customer_has_unread_team_count_one(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _customer_user_info()
        mock_client.return_value = MagicMock()

        ticket = create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_CUST",
            text="Help me please",
            slack_team_id=SLACK_TEAM,
        )

        assert ticket is not None
        ticket.refresh_from_db()
        assert ticket.unread_team_count == 1

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_new_ticket_from_customer_sets_customer_author_type(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _customer_user_info()
        mock_client.return_value = MagicMock()

        ticket = create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_CUST",
            text="Help me",
            slack_team_id=SLACK_TEAM,
        )

        assert ticket is not None
        comment = Comment.objects.get(item_id=str(ticket.id))
        assert comment.item_context["author_type"] == "customer"
        assert comment.item_context["from_slack"] is True
        assert comment.created_by is None

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_thread_reply_from_team_member_does_not_increment_unread_team(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _team_member_user_info(self.user.email)
        mock_client.return_value = MagicMock()

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL_ID,
            slack_thread_ts=PARENT_TS,
            unread_team_count=1,
        )

        create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_TEAM",
            text="Team member reply",
            is_thread_reply=True,
            slack_team_id=SLACK_TEAM,
        )

        ticket.refresh_from_db()
        assert ticket.unread_team_count == 1  # unchanged

    @patch(f"{MODULE}.get_slack_client")
    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_thread_reply_from_customer_increments_unread_team(self, _files, mock_resolve, mock_client):
        mock_resolve.return_value = _customer_user_info()
        mock_client.return_value = MagicMock()

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL_ID,
            slack_thread_ts=PARENT_TS,
            unread_team_count=1,
        )

        create_or_update_slack_ticket(
            team=self.team,
            slack_channel_id=CHANNEL_ID,
            thread_ts=PARENT_TS,
            slack_user_id="U_CUST",
            text="Customer reply",
            is_thread_reply=True,
            slack_team_id=SLACK_TEAM,
        )

        ticket.refresh_from_db()
        assert ticket.unread_team_count == 2


class TestBackfillTeamMemberDetection(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.SLACK,
            widget_session_id="",
            distinct_id="",
            slack_channel_id=CHANNEL_ID,
            slack_thread_ts=PARENT_TS,
            unread_team_count=1,
            unread_customer_count=0,
        )

    def _mock_client(self, replies: list[dict]) -> MagicMock:
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": replies}
        return client

    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_backfill_splits_unread_counts_by_author_type(self, _files, mock_resolve):
        def resolve_side_effect(client, slack_user_id):
            if slack_user_id == "U_TEAM":
                return _team_member_user_info(self.user.email)
            return _customer_user_info()

        mock_resolve.side_effect = resolve_side_effect

        replies = [
            {"ts": PARENT_TS, "user": "U_CUST", "text": "parent"},
            {"ts": "1700000000.000200", "user": "U_CUST", "text": "customer reply"},
            {"ts": "1700000000.000300", "user": "U_TEAM", "text": "team reply"},
            {"ts": "1700000000.000400", "user": "U_CUST", "text": "another customer reply"},
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL_ID, PARENT_TS)

        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 3  # 1 original + 2 customer replies
        assert self.ticket.unread_customer_count == 1  # 1 team reply

        comments = Comment.objects.filter(item_id=str(self.ticket.id)).order_by("created_at")
        customer_comments = [c for c in comments if c.item_context["author_type"] == "customer"]
        team_comments = [c for c in comments if c.item_context["author_type"] == "support"]
        assert len(customer_comments) == 2
        assert len(team_comments) == 1
        assert team_comments[0].created_by_id == self.user.id

    @patch(f"{MODULE}.resolve_slack_user")
    @patch(f"{MODULE}.extract_slack_files", return_value=[])
    def test_backfill_all_customer_messages_only_increments_unread_team(self, _files, mock_resolve):
        mock_resolve.return_value = _customer_user_info()

        replies = [
            {"ts": PARENT_TS, "user": "U_CUST", "text": "parent"},
            {"ts": "1700000000.000200", "user": "U_CUST", "text": "reply 1"},
            {"ts": "1700000000.000300", "user": "U_CUST2", "text": "reply 2"},
        ]
        client = self._mock_client(replies)

        _backfill_thread_replies(client, self.team, self.ticket, CHANNEL_ID, PARENT_TS)

        self.ticket.refresh_from_db()
        assert self.ticket.unread_team_count == 3  # 1 original + 2 backfilled
        assert self.ticket.unread_customer_count == 0  # no team messages


@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestSlackEchoPreventionSignal(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        self.slack_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="slack-user",
            channel_source=Channel.SLACK,
            slack_channel_id=CHANNEL_ID,
            slack_thread_ts=PARENT_TS,
        )

    @patch("products.conversations.backend.tasks.post_reply_to_slack.delay")
    def test_from_slack_team_message_does_not_echo_back(self, mock_delay, _on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.slack_ticket.id),
            content="Team member replied in Slack",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False, "from_slack": True},
        )

        mock_delay.assert_not_called()

    @patch("products.conversations.backend.tasks.post_reply_to_slack.delay")
    def test_posthog_ui_team_message_does_echo_to_slack(self, mock_delay, _on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.slack_ticket.id),
            content="Reply from PostHog UI",
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

        mock_delay.assert_called_once()

    @patch("products.conversations.backend.tasks.post_reply_to_slack.delay")
    def test_from_slack_customer_message_does_not_echo(self, mock_delay, _on_commit):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.slack_ticket.id),
            content="Customer message from Slack",
            item_context={"author_type": "customer", "is_private": False, "from_slack": True},
        )

        mock_delay.assert_not_called()
