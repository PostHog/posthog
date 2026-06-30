import uuid
import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel

from ee.billing.salesforce_enrichment.conversations_signals import (
    aggregate_conversations_slack_signals_for_orgs,
    build_slack_channel_url,
    build_support_ticket_url,
    fetch_slack_channel_user_count,
)


class TestConversationsSlackSignals(SimpleTestCase):
    def test_builds_channel_url(self):
        assert build_slack_channel_url("C123", "T123") == "https://app.slack.com/client/T123/C123"
        assert build_slack_channel_url("C123") == "https://app.slack.com/archives/C123"

    def test_builds_support_ticket_url(self):
        with self.settings(SITE_URL="https://us.posthog.com"):
            assert build_support_ticket_url(2, 1234) == "https://us.posthog.com/project/2/support/tickets/1234"

    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_aggregates_latest_channel_for_org(self, mock_fetch_rows, mock_fetch_latest_tickets):
        org_id = "org-1"
        mock_fetch_rows.return_value = [
            {
                "organization_id": org_id,
                "slack_channel_id": "C_NEW",
                "slack_team_id": "T123",
                "team_id": 1,
                "slack_issue_count": 2,
                "last_slack_activity": dt.datetime(2026, 6, 29, 9, 0, tzinfo=dt.UTC),
            },
            {
                "organization_id": org_id,
                "slack_channel_id": "C_OLD",
                "slack_team_id": "T123",
                "team_id": 1,
                "slack_issue_count": 1,
                "last_slack_activity": dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
            },
        ]
        mock_fetch_latest_tickets.return_value = [
            {
                "organization_id": org_id,
                "team_id": 2,
                "ticket_number": 1234,
                "activity_at": dt.datetime(2026, 6, 30, 8, 0, tzinfo=dt.UTC),
            }
        ]

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs([org_id], include_slack_user_count=False)

        assert set(result.keys()) == {org_id}
        signals = result[org_id]
        assert signals.posthog_organization_id == org_id
        assert signals.slack_channel_url == "https://app.slack.com/client/T123/C_NEW"
        assert signals.slack_issue_count == 2
        assert signals.slack_user_count is None
        assert signals.last_slack_activity == dt.datetime(2026, 6, 29, 9, 0, tzinfo=dt.UTC)
        assert signals.most_recent_support_ticket_url == "https://us.posthog.com/project/2/support/tickets/1234"

    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_returns_latest_support_ticket_without_slack_rows(self, mock_fetch_rows, mock_fetch_latest_tickets):
        org_id = "org-1"
        mock_fetch_rows.return_value = []
        mock_fetch_latest_tickets.return_value = [
            {
                "organization_id": org_id,
                "team_id": 2,
                "ticket_number": 5678,
                "activity_at": dt.datetime(2026, 6, 30, 8, 0, tzinfo=dt.UTC),
            }
        ]

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs([org_id], include_slack_user_count=False)

        assert set(result.keys()) == {org_id}
        signals = result[org_id]
        assert signals.slack_channel_url is None
        assert signals.slack_issue_count == 0
        assert signals.slack_user_count is None
        assert signals.last_slack_activity is None
        assert signals.most_recent_support_ticket_url == "https://us.posthog.com/project/2/support/tickets/5678"

    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_returns_empty_when_no_rows(self, mock_fetch_rows, mock_fetch_latest_tickets):
        mock_fetch_rows.return_value = []
        mock_fetch_latest_tickets.return_value = []

        result = aggregate_conversations_slack_signals_for_orgs(["org-1"], include_slack_user_count=False)

        assert result == {}

    @patch("ee.billing.salesforce_enrichment.conversations_signals.WebClient")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._get_slack_bot_token_for_team")
    def test_fetch_slack_channel_user_count_paginates(self, mock_get_token, mock_web_client):
        mock_get_token.return_value = "xoxb-test"
        mock_client = MagicMock()
        mock_client.conversations_members.side_effect = [
            {"members": ["U1", "U2"], "response_metadata": {"next_cursor": "next-page"}},
            {"members": ["U3"], "response_metadata": {}},
        ]
        mock_web_client.return_value = mock_client

        result = fetch_slack_channel_user_count(1, "C123")

        assert result == 3
        assert mock_client.conversations_members.call_args_list[0].kwargs["cursor"] is None
        assert mock_client.conversations_members.call_args_list[1].kwargs["cursor"] == "next-page"


class TestConversationsSlackSignalsDatabase(BaseTest):
    def _create_slack_ticket(
        self,
        *,
        org_id: str,
        channel_id: str,
        activity_at: dt.datetime,
        slack_team_id: str | None = "T123",
    ) -> Ticket:
        return Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=f"session-{uuid.uuid4()}",
            distinct_id=f"user-{uuid.uuid4()}",
            channel_source=Channel.SLACK,
            slack_channel_id=channel_id,
            slack_team_id=slack_team_id,
            organization_id=org_id,
            last_message_at=activity_at,
        )

    def test_aggregate_query_merges_channel_workspace_fragments_and_applies_ordering(self):
        org_with_mixed_workspace = "org-mixed-workspace"
        selected_activity = dt.datetime(2026, 6, 30, 11, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(
            org_id=org_with_mixed_workspace,
            channel_id="C_SHARED",
            activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC),
            slack_team_id="T123",
        )
        most_recent_ticket = self._create_slack_ticket(
            org_id=org_with_mixed_workspace,
            channel_id="C_SHARED",
            activity_at=selected_activity,
            slack_team_id=None,
        )
        for index in range(3):
            self._create_slack_ticket(
                org_id=org_with_mixed_workspace,
                channel_id="C_OLD_BUSY",
                activity_at=dt.datetime(2026, 6, 29, 12, index, tzinfo=dt.UTC),
                slack_team_id="T123",
            )

        org_with_tie = "org-tie"
        tie_activity = dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.UTC)
        for channel_id in ("C_TIE_B", "C_TIE_A"):
            self._create_slack_ticket(org_id=org_with_tie, channel_id=channel_id, activity_at=tie_activity)
            self._create_slack_ticket(org_id=org_with_tie, channel_id=channel_id, activity_at=tie_activity)
        self._create_slack_ticket(org_id=org_with_tie, channel_id="C_TIE_C", activity_at=tie_activity)

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs(
                [org_with_mixed_workspace, org_with_tie],
                include_slack_user_count=False,
            )

        mixed_workspace_signals = result[org_with_mixed_workspace]
        assert mixed_workspace_signals.slack_channel_url == "https://app.slack.com/client/T123/C_SHARED"
        assert mixed_workspace_signals.slack_issue_count == 2
        assert mixed_workspace_signals.last_slack_activity == selected_activity
        assert (
            mixed_workspace_signals.most_recent_support_ticket_url
            == f"https://us.posthog.com/project/{self.team.id}/support/tickets/{most_recent_ticket.ticket_number}"
        )

        tie_signals = result[org_with_tie]
        assert tie_signals.slack_channel_url == "https://app.slack.com/client/T123/C_TIE_A"
        assert tie_signals.slack_issue_count == 2
        assert tie_signals.last_slack_activity == tie_activity
