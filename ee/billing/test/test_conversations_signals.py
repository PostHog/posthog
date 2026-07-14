import uuid
import datetime as dt
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, User

from products.conversations.backend.models import TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import Channel

from ee.billing.salesforce_enrichment.conversations_signals import (
    _get_slack_bot_token,
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
                "representative_team_id": 1,
                "slack_issue_count": 2,
                "last_slack_activity": dt.datetime(2026, 6, 29, 9, 0, tzinfo=dt.UTC),
            },
            {
                "organization_id": org_id,
                "slack_channel_id": "C_OLD",
                "slack_team_id": "T123",
                "representative_team_id": 1,
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
    @patch("ee.billing.salesforce_enrichment.conversations_signals._get_slack_bot_token")
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
    def setUp(self) -> None:
        super().setUp()
        self.org_id = str(self.organization.id)

    def _create_slack_ticket(
        self,
        *,
        channel_id: str,
        activity_at: dt.datetime,
        org_id: str | None = None,
        slack_team_id: str | None = "T123",
        distinct_id: str | None = None,
        identity_verified: bool | None = True,
    ) -> Ticket:
        return Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=f"session-{uuid.uuid4()}",
            distinct_id=self.user.distinct_id if distinct_id is None else distinct_id,
            channel_source=Channel.SLACK,
            slack_channel_id=channel_id,
            slack_team_id=slack_team_id,
            organization_id=org_id or self.org_id,
            last_message_at=activity_at,
            identity_verified=identity_verified,
        )

    def _create_member_of_other_org(self, email: str) -> tuple[Organization, User]:
        organization = Organization.objects.create(name=f"other-{uuid.uuid4()}")
        user = User.objects.create_and_join(organization, email, None)
        return organization, user

    def test_aggregate_query_applies_recency_and_tie_break_ordering(self):
        selected_activity = dt.datetime(2026, 6, 30, 11, 0, tzinfo=dt.UTC)
        most_recent_ticket = self._create_slack_ticket(channel_id="C_NEW", activity_at=selected_activity)
        for index in range(3):
            self._create_slack_ticket(
                channel_id="C_OLD_BUSY",
                activity_at=dt.datetime(2026, 6, 29, 12, index, tzinfo=dt.UTC),
            )

        tie_org, tie_user = self._create_member_of_other_org(f"tie-{uuid.uuid4()}@posthog.com")
        tie_org_id = str(tie_org.id)
        tie_activity = dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.UTC)
        for channel_id in ("C_TIE_B", "C_TIE_A"):
            for _ in range(2):
                self._create_slack_ticket(
                    org_id=tie_org_id,
                    channel_id=channel_id,
                    activity_at=tie_activity,
                    distinct_id=tie_user.distinct_id,
                )
        self._create_slack_ticket(
            org_id=tie_org_id, channel_id="C_TIE_C", activity_at=tie_activity, distinct_id=tie_user.distinct_id
        )

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs(
                [self.org_id, tie_org_id],
                include_slack_user_count=False,
            )

        signals = result[self.org_id]
        assert signals.slack_channel_url == "https://app.slack.com/client/T123/C_NEW"
        assert signals.slack_issue_count == 1
        assert signals.last_slack_activity == selected_activity
        assert (
            signals.most_recent_support_ticket_url
            == f"https://us.posthog.com/project/{self.team.id}/support/tickets/{most_recent_ticket.ticket_number}"
        )

        tie_signals = result[tie_org_id]
        assert tie_signals.slack_channel_url == "https://app.slack.com/client/T123/C_TIE_A"
        assert tie_signals.slack_issue_count == 2
        assert tie_signals.last_slack_activity == tie_activity

    @parameterized.expand(
        [
            ("member_distinct_id", lambda self: {"distinct_id": self.user.distinct_id}, True),
            ("member_email_as_distinct_id", lambda self: {"distinct_id": self.user.email.upper()}, True),
            ("unknown_identity", lambda self: {"distinct_id": f"stranger-{uuid.uuid4()}"}, False),
            (
                "identity_verification_failed",
                lambda self: {"distinct_id": self.user.distinct_id, "identity_verified": False},
                False,
            ),
            (
                "identity_never_verified",
                lambda self: {"distinct_id": self.user.distinct_id, "identity_verified": None},
                False,
            ),
        ]
    )
    def test_only_tickets_with_verified_org_attribution_count(
        self,
        _name: str,
        ticket_kwargs: Callable[["TestConversationsSlackSignalsDatabase"], dict[str, Any]],
        expected_included: bool,
    ) -> None:
        self._create_slack_ticket(
            channel_id="C123",
            activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC),
            **ticket_kwargs(self),
        )

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        assert (self.org_id in result) == expected_included

    def test_malformed_org_id_is_excluded_without_breaking_aggregation(self):
        malformed_org_id = "not-a-uuid"
        self._create_slack_ticket(
            org_id=malformed_org_id,
            channel_id="C123",
            activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC),
        )

        result = aggregate_conversations_slack_signals_for_orgs(
            [malformed_org_id, self.org_id], include_slack_user_count=False
        )

        assert result == {}

    def test_spoofed_org_attribution_does_not_poison_another_orgs_signals(self):
        legit_ticket = self._create_slack_ticket(
            channel_id="C_LEGIT", activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC)
        )
        # The attacker is a genuine member of their own org, but stamps the victim's
        # org id on a ticket (as spoofed analytics $groups attribution would).
        _, attacker = self._create_member_of_other_org(f"attacker-{uuid.uuid4()}@posthog.com")
        self._create_slack_ticket(
            org_id=self.org_id,
            channel_id="C_EVIL",
            activity_at=dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC),
            distinct_id=attacker.distinct_id,
        )

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        signals = result[self.org_id]
        assert signals.slack_channel_url == "https://app.slack.com/client/T123/C_LEGIT"
        assert signals.slack_issue_count == 1
        assert (
            signals.most_recent_support_ticket_url
            == f"https://us.posthog.com/project/{self.team.id}/support/tickets/{legit_ticket.ticket_number}"
        )

    def test_email_channel_ticket_verified_by_email_from(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=f"session-{uuid.uuid4()}",
            distinct_id="",
            channel_source=Channel.EMAIL,
            email_from=self.user.email.upper(),
            organization_id=self.org_id,
            last_message_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC),
            identity_verified=True,
        )

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        signals = result[self.org_id]
        assert signals.slack_channel_url is None
        assert signals.slack_issue_count == 0
        assert (
            signals.most_recent_support_ticket_url
            == f"https://us.posthog.com/project/{self.team.id}/support/tickets/{ticket.ticket_number}"
        )

    def test_channels_with_same_id_in_different_workspaces_are_not_merged(self):
        self._create_slack_ticket(
            channel_id="C_SHARED",
            activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC),
            slack_team_id="T_ONE",
        )
        self._create_slack_ticket(
            channel_id="C_SHARED",
            activity_at=dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC),
            slack_team_id="T_TWO",
        )

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        signals = result[self.org_id]
        assert signals.slack_channel_url == "https://app.slack.com/client/T_TWO/C_SHARED"
        assert signals.slack_issue_count == 1

    def test_get_slack_bot_token_resolves_by_workspace_then_team(self):
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team, defaults={"slack_team_id": "TWORK", "slack_bot_token": "xoxb-test"}
        )

        # Matches by Slack workspace id, independent of the representative team.
        assert _get_slack_bot_token("TWORK", None) == "xoxb-test"
        # Falls back to the representative team when the workspace id is absent or unmatched.
        assert _get_slack_bot_token(None, self.team.id) == "xoxb-test"
        assert _get_slack_bot_token("TUNMATCHED", self.team.id) == "xoxb-test"
        # No token when neither path resolves.
        assert _get_slack_bot_token("TUNMATCHED", None) is None
