from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.channel_summary_ids import build_channel_summary_workflow_id
from products.conversations.backend.facade.api import (
    SupportMessageSendError,
    get_public_human_replies,
    list_account_ticket_messages,
    list_account_tickets,
    list_resolved_ticket_revisions,
    post_support_message,
    trigger_immediate_channel_summary,
)
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket

CLIENT = "products.conversations.backend.facade.api.get_slack_client"
FACADE = "products.conversations.backend.facade.api"


class FakeSlackResponse(dict):
    # Mimics slack_sdk's SlackResponse: .get() reads the JSON body, HTTP headers are an attribute.
    def __init__(self, data: dict, headers: dict | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class TestPostSupportMessage(BaseTest):
    @patch(CLIENT)
    def test_applies_configured_bot_identity(self, mock_get_client: MagicMock):
        self.team.conversations_settings = {
            "slack_bot_display_name": "SupportBot",
            "slack_bot_icon_url": "https://example.com/icon.png",
        }
        self.team.save()
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "111.222"}
        mock_get_client.return_value = client

        ts = post_support_message(self.team.pk, "C1", "hello team")

        assert ts == "111.222"
        kwargs = client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["text"] == "hello team"
        assert kwargs["username"] == "SupportBot"
        assert kwargs["icon_url"] == "https://example.com/icon.png"

    @parameterized.expand(
        [
            (
                "slack_rate_limited",
                SlackApiError(
                    message="x",
                    response=FakeSlackResponse({"error": "ratelimited"}, headers={"Retry-After": "7"}),
                ),
                None,
                "ratelimited",
                7.0,
            ),
            ("transport_error", ConnectionError("boom"), None, "transport_error", None),
            ("missing_ts", None, {"ok": True}, "missing_ts", None),
        ]
    )
    @patch(CLIENT)
    def test_translates_send_failures(
        self,
        _name: str,
        side_effect: Exception | None,
        return_value: dict | None,
        expected_code: str,
        expected_retry_after: float | None,
        mock_get_client: MagicMock,
    ):
        client = MagicMock()
        if side_effect is not None:
            client.chat_postMessage.side_effect = side_effect
        else:
            client.chat_postMessage.return_value = return_value
        mock_get_client.return_value = client

        with self.assertRaises(SupportMessageSendError) as ctx:
            post_support_message(self.team.pk, "C1", "hi")
        assert ctx.exception.code == expected_code
        assert ctx.exception.retry_after == expected_retry_after


class TestListAccountTickets(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.access_control = MagicMock()
        self.access_control.filter_queryset_by_access_level.side_effect = lambda queryset: queryset

    def _create_ticket(self, *, team: Team, organization_id: str | None, number: int, last_message_at=None) -> Ticket:
        return Ticket.objects.create(
            team=team,
            ticket_number=number,
            widget_session_id=f"s{number}",
            distinct_id=f"d{number}",
            organization_id=organization_id,
            last_message_at=last_message_at,
        )

    def test_returns_only_tickets_for_this_team_and_org(self):
        other_team = Team.objects.create(organization=self.organization)
        mine = self._create_ticket(team=self.team, organization_id="acct-1", number=1)
        self._create_ticket(team=self.team, organization_id="acct-2", number=2)
        self._create_ticket(team=other_team, organization_id="acct-1", number=1)

        result = list_account_tickets(self.team.pk, "acct-1", self.access_control)

        assert [t.id for t in result] == [str(mine.id)]
        assert result[0].deep_link.endswith(f"/project/{self.team.pk}/support/tickets/1")

    def test_returns_latest_public_message_sender(self):
        ticket = self._create_ticket(
            team=self.team,
            organization_id="acct-1",
            number=1,
            last_message_at=timezone.now(),
        )
        ticket.anonymous_traits = {"name": "Example customer", "email": "customer@example.com"}
        ticket.save(update_fields=["anonymous_traits"])
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Support reply",
            item_context={"author_type": "support", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Customer reply",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Private note",
            item_context={"author_type": "support", "is_private": True},
        )

        result = list_account_tickets(self.team.pk, "acct-1", self.access_control)

        assert result[0].last_message is not None
        assert result[0].last_message.sender.name == "Example customer"
        assert result[0].last_message.sender.email == "customer@example.com"
        assert result[0].last_message.sender.distinct_id == ticket.distinct_id
        assert result[0].last_message.direction == "inbound"

        message_page = list_account_ticket_messages(self.team.pk, "acct-1", str(ticket.id), self.access_control)
        assert message_page is not None
        messages, count = message_page
        assert count == 3
        assert [message.content for message in messages] == ["Support reply", "Customer reply", "Private note"]
        assert [message.direction for message in messages] == ["outbound", "inbound", "outbound"]
        assert messages[-1].is_private is True

    def test_returns_imported_support_sender_without_a_posthog_user(self):
        ticket = self._create_ticket(
            team=self.team,
            organization_id="acct-1",
            number=1,
            last_message_at=timezone.now(),
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Imported support reply",
            item_context={
                "author_type": "support",
                "author_name": "Imported agent",
                "author_email": "agent@example.com",
                "is_private": False,
            },
        )

        result = list_account_tickets(self.team.pk, "acct-1", self.access_control)

        assert result[0].last_message is not None
        assert result[0].last_message.sender.name == "Imported agent"
        assert result[0].last_message.sender.email == "agent@example.com"
        assert result[0].last_message.direction == "outbound"

    @parameterized.expand(
        [
            (
                "slack",
                {
                    "author_type": "customer",
                    "slack_author_name": "Slack responder",
                    "slack_author_email": "slack@example.com",
                },
                "Slack responder",
                "slack@example.com",
            ),
            (
                "teams",
                {
                    "author_type": "customer",
                    "teams_author_name": "Teams responder",
                    "teams_author_email": "teams@example.com",
                },
                "Teams responder",
                "teams@example.com",
            ),
            (
                "email",
                {"author_type": "customer", "email_from_name": "Email responder", "email_from": "email@example.com"},
                "Email responder",
                "email@example.com",
            ),
        ]
    )
    def test_returns_channel_specific_inbound_sender(
        self,
        _name: str,
        item_context: dict[str, str],
        expected_name: str,
        expected_email: str,
    ) -> None:
        ticket = self._create_ticket(
            team=self.team,
            organization_id="acct-1",
            number=1,
            last_message_at=timezone.now(),
        )
        ticket.anonymous_traits = {"name": "Thread starter", "email": "starter@example.com"}
        ticket.save(update_fields=["anonymous_traits"])
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Channel reply",
            item_context=item_context,
        )

        tickets = list_account_tickets(self.team.pk, "acct-1", self.access_control)
        message_page = list_account_ticket_messages(self.team.pk, "acct-1", str(ticket.id), self.access_control)

        assert tickets[0].last_message is not None
        assert tickets[0].last_message.sender.name == expected_name
        assert tickets[0].last_message.sender.email == expected_email
        assert message_page is not None
        assert message_page[0][0].author_name == expected_name

    def test_orders_by_last_message_activity_with_nulls_last(self):
        older = timezone.now() - timedelta(hours=1)
        newer = timezone.now()
        self._create_ticket(team=self.team, organization_id="acct-1", number=1, last_message_at=older)
        self._create_ticket(team=self.team, organization_id="acct-1", number=2, last_message_at=newer)
        self._create_ticket(team=self.team, organization_id="acct-1", number=3, last_message_at=None)

        result = list_account_tickets(self.team.pk, "acct-1", self.access_control)

        assert [t.ticket_number for t in result] == [2, 1, 3]

    def test_empty_organization_id_matches_nothing(self):
        self._create_ticket(team=self.team, organization_id="acct-1", number=1)

        assert list_account_tickets(self.team.pk, "", self.access_control) == []


ACCOUNT_ID = "e1f4a5b6-0000-4000-8000-000000000001"
PERIOD_START = datetime(2026, 7, 27, tzinfo=UTC)


class TestTriggerImmediateChannelSummary(BaseTest):
    def _trigger(self) -> bool:
        return trigger_immediate_channel_summary(
            team_id=self.team.pk,
            account_id=ACCOUNT_ID,
            account_name="Acme Corp",
            slack_channel_id="C123",
            cadence="daily",
            period_start=PERIOD_START,
            period_end=PERIOD_START + timedelta(days=1),
        )

    @parameterized.expand(
        [
            ("eligible", True, "xoxb-token", True),
            ("ai_processing_not_approved", False, "xoxb-token", False),
            ("support_bot_not_configured", True, "", False),
        ]
    )
    def test_gates_on_org_approval_and_bot_config(self, _name, ai_approved, bot_token, expected_dispatch):
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()

        with (
            patch(f"{FACADE}.get_support_slack_bot_token", return_value=bot_token),
            patch(f"{FACADE}.sync_connect") as connect,
            patch(f"{FACADE}.asyncio.run") as run,
        ):
            dispatched = self._trigger()

        assert dispatched is expected_dispatch
        assert connect.called is expected_dispatch
        assert run.called is expected_dispatch

    def test_dispatches_under_the_shared_workflow_id(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        client = MagicMock()

        with (
            patch(f"{FACADE}.get_support_slack_bot_token", return_value="xoxb-token"),
            patch(f"{FACADE}.sync_connect", return_value=client),
            patch(f"{FACADE}.asyncio.run"),
        ):
            self._trigger()

        assert client.start_workflow.call_args.kwargs["id"] == build_channel_summary_workflow_id(
            account_id=ACCOUNT_ID, cadence="daily", period_start=PERIOD_START.date()
        )
        assert client.start_workflow.call_args.args[1].slack_channel_id == "C123"


LOOKBACK = timedelta(days=7)


class TestResolvedTicketEvidence(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.since = timezone.now() - LOOKBACK

    def _ticket(self, *, team: Team | None = None, status: str = Status.RESOLVED, number: int = 1) -> Ticket:
        team = team or self.team
        return Ticket.objects.create(
            team=team,
            ticket_number=number,
            widget_session_id=f"s{number}-{team.id}",
            distinct_id=f"d{number}-{team.id}",
            status=status,
        )

    def _comment(
        self,
        ticket: Ticket,
        *,
        author_type: str,
        content: str,
        is_private: bool | None = False,
        deleted: bool = False,
        extra_context: dict[str, str] | None = None,
    ) -> Comment:
        item_context: dict = {"author_type": author_type}
        if is_private is not None:
            item_context["is_private"] = is_private
        if extra_context:
            item_context.update(extra_context)
        return Comment.objects.create(
            team=ticket.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            deleted=deleted,
            item_context=item_context,
        )

    def _revisions(self, *, team: Team | None = None, limit: int = 10):
        return list_resolved_ticket_revisions((team or self.team).id, since=self.since, limit=limit)

    def test_returns_only_public_human_reply_text(self) -> None:
        ticket = self._ticket()
        self._comment(
            ticket,
            author_type="customer",
            content="Customer asked about the rate limit",
            extra_context={"author_name": "Ada", "author_email": "ada@example.com"},
        )
        human = self._comment(
            ticket,
            author_type="support",
            content="The rate limit is 1000 events per hour",
            extra_context={"author_name": "Support agent", "author_email": "agent@example.com"},
        )
        self._comment(ticket, author_type="support", content="Private diagnosis", is_private=True)
        self._comment(ticket, author_type="AI", content="AI suggested a reply")
        self._comment(ticket, author_type="team", content="Team analytics author type")

        revisions = self._revisions()
        replies = get_public_human_replies(self.team.id, ticket.id)

        assert [revision.ticket_id for revision in revisions] == [ticket.id]
        assert revisions[0].resolution_comment_id == human.id
        assert replies is not None
        assert replies.replies == ("The rate limit is 1000 events per hour",)

    @parameterized.expand(
        [
            ("customer", "customer", False, False, "Customer said this"),
            ("ai", "AI", False, False, "AI drafted this"),
            ("team", "team", False, False, "Team analytics type"),
            ("private_support", "support", True, False, "Internal note"),
            ("deleted_support", "support", False, True, "Retracted reply"),
            ("empty_content", "support", False, False, ""),
            ("whitespace_only", "support", False, False, "   "),
        ]
    )
    def test_collect_skips_tickets_without_a_public_human_reply(
        self,
        _name: str,
        author_type: str,
        is_private: bool,
        deleted: bool,
        content: str,
    ) -> None:
        ticket = self._ticket()
        self._comment(
            ticket,
            author_type=author_type,
            content=content,
            is_private=is_private,
            deleted=deleted,
        )

        assert self._revisions() == []
        assert get_public_human_replies(self.team.id, ticket.id) is None

    @parameterized.expand(
        [
            ("support", "support", False),
            ("human", "human", False),
            ("missing_is_private_key", "support", None),
        ]
    )
    def test_collect_includes_public_human_author_types(
        self,
        _name: str,
        author_type: str,
        is_private: bool | None,
    ) -> None:
        ticket = self._ticket()
        comment = self._comment(ticket, author_type=author_type, content="Reusable answer", is_private=is_private)

        revisions = self._revisions()
        replies = get_public_human_replies(self.team.id, ticket.id)

        assert [revision.resolution_comment_id for revision in revisions] == [comment.id]
        assert replies is not None
        assert replies.replies == ("Reusable answer",)

    def test_revision_follows_the_latest_public_human_comment(self) -> None:
        ticket = self._ticket()
        first = self._comment(ticket, author_type="support", content="First answer")
        later = self._comment(ticket, author_type="human", content="Follow-up answer")
        self._comment(ticket, author_type="AI", content="Later AI note")
        self._comment(ticket, author_type="support", content="Deleted later", deleted=True)
        now = timezone.now()
        Comment.objects.filter(pk=first.id).update(created_at=now - timedelta(minutes=2))
        Comment.objects.filter(pk=later.id).update(created_at=now - timedelta(minutes=1))

        revisions = self._revisions()
        replies = get_public_human_replies(self.team.id, ticket.id)
        pinned = get_public_human_replies(self.team.id, ticket.id, resolution_comment_id=first.id)

        assert [revision.resolution_comment_id for revision in revisions] == [later.id]
        assert replies is not None
        assert replies.replies == ("First answer", "Follow-up answer")
        assert pinned is not None
        assert pinned.replies == ("First answer",)
        assert get_public_human_replies(self.team.id, ticket.id, resolution_comment_id=uuid4()) is None

    def test_open_ticket_is_not_collected(self) -> None:
        ticket = self._ticket(status=Status.OPEN)
        self._comment(ticket, author_type="support", content="Still working on it")

        assert self._revisions() == []
        replies = get_public_human_replies(self.team.id, ticket.id)
        assert replies is not None
        assert replies.replies == ("Still working on it",)

    def test_conversations_disabled_returns_nothing(self) -> None:
        ticket = self._ticket()
        self._comment(ticket, author_type="support", content="Reusable answer")
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])

        assert self._revisions() == []
        assert get_public_human_replies(self.team.id, ticket.id) is None

    def test_does_not_return_other_teams_tickets(self) -> None:
        other = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        other.conversations_enabled = True
        other.save(update_fields=["conversations_enabled"])
        other_ticket = self._ticket(team=other, number=1)
        self._comment(other_ticket, author_type="support", content="Other team answer")

        assert self._revisions() == []
        assert get_public_human_replies(self.team.id, other_ticket.id) is None

    def test_child_environment_reads_comments_stored_on_the_parent(self) -> None:
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
            conversations_enabled=True,
        )
        ticket = self._ticket(team=child)
        comment = self._comment(ticket, author_type="support", content="Answer from the child environment")

        revisions = self._revisions(team=child)
        replies = get_public_human_replies(child.id, ticket.id)

        assert comment.team_id == self.team.id
        assert [revision.source_team_id for revision in revisions] == [child.id]
        assert revisions[0].resolution_comment_id == comment.id
        assert self._revisions() == []
        assert replies is not None
        assert replies.replies == ("Answer from the child environment",)

    def test_lookback_excludes_stale_resolved_tickets(self) -> None:
        ticket = self._ticket()
        self._comment(ticket, author_type="support", content="Old answer")
        stale = timezone.now() - timedelta(days=8)
        Ticket.objects.filter(pk=ticket.id).update(updated_at=stale, last_message_at=stale)

        assert self._revisions() == []

    def test_limit_returns_the_most_recently_updated_ticket(self) -> None:
        older = self._ticket(number=1)
        newer = self._ticket(number=2)
        self._comment(older, author_type="support", content="Older answer")
        self._comment(newer, author_type="support", content="Newer answer")
        Ticket.objects.filter(pk=older.id).update(updated_at=timezone.now() - timedelta(hours=2))
        Ticket.objects.filter(pk=newer.id).update(updated_at=timezone.now() - timedelta(hours=1))

        revisions = self._revisions(limit=1)

        assert [revision.ticket_id for revision in revisions] == [newer.id]
        assert revisions[0].display_label == "ticket #2"
        assert revisions[0].deep_link == f"{settings.SITE_URL}/project/{self.team.id}/support/tickets/2"
