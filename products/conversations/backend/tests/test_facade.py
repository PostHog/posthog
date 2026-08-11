from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team

from products.conversations.backend.channel_summary_ids import build_channel_summary_workflow_id
from products.conversations.backend.facade.api import (
    SupportMessageSendError,
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

        result = list_account_tickets(self.team.pk, "acct-1")

        assert [t.id for t in result] == [str(mine.id)]
        assert result[0].deep_link.endswith(f"/project/{self.team.pk}/support/tickets/1")

    def test_orders_by_last_message_activity_with_nulls_last(self):
        older = timezone.now() - timedelta(hours=1)
        newer = timezone.now()
        self._create_ticket(team=self.team, organization_id="acct-1", number=1, last_message_at=older)
        self._create_ticket(team=self.team, organization_id="acct-1", number=2, last_message_at=newer)
        self._create_ticket(team=self.team, organization_id="acct-1", number=3, last_message_at=None)

        result = list_account_tickets(self.team.pk, "acct-1")

        assert [t.ticket_number for t in result] == [2, 1, 3]

    def test_empty_organization_id_matches_nothing(self):
        self._create_ticket(team=self.team, organization_id="acct-1", number=1)

        assert list_account_tickets(self.team.pk, "") == []


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
