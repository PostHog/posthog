from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models import Team

from products.conversations.backend.facade.api import (
    SupportMessageSendError,
    list_account_tickets,
    post_support_message,
)
from products.conversations.backend.models.ticket import Ticket

CLIENT = "products.conversations.backend.facade.api.get_slack_client"


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
