from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.channel_summary_ids import build_channel_summary_workflow_id
from products.conversations.backend.facade.api import (
    SupportMessageSendError,
    list_account_ticket_messages,
    list_account_tickets,
    post_support_message,
    trigger_immediate_channel_summary,
)
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
