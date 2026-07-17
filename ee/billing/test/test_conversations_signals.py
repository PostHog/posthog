import uuid
import datetime as dt
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.comment import Comment

from products.conversations.backend.models import TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import Channel

from ee.billing.salesforce_enrichment.conversations_signals import (
    _fetch_slack_bot_joined_at_by_channel,
    _get_slack_bot_token,
    _lookup_slack_bot_joined_at,
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

    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_bot_joined_at_by_channel")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_last_customer_message_at_by_org")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_trusted_slack_channel_activity_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_aggregates_latest_channel_for_org(
        self,
        mock_fetch_rows,
        mock_fetch_channel_activity,
        mock_fetch_latest_tickets,
        mock_fetch_last_customer,
        mock_fetch_bot_joined,
    ):
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
        mock_fetch_channel_activity.return_value = []
        mock_fetch_latest_tickets.return_value = [
            {
                "organization_id": org_id,
                "team_id": 2,
                "ticket_number": 1234,
                "activity_at": dt.datetime(2026, 6, 30, 8, 0, tzinfo=dt.UTC),
            }
        ]
        mock_fetch_last_customer.return_value = {org_id: dt.datetime(2026, 6, 28, 14, 30, tzinfo=dt.UTC)}
        mock_fetch_bot_joined.return_value = {("T123", "C_NEW"): dt.datetime(2026, 7, 5, 9, 0, tzinfo=dt.UTC)}

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
        assert signals.last_customer_message_at == dt.datetime(2026, 6, 28, 14, 30, tzinfo=dt.UTC)
        assert signals.slack_bot_joined_at == dt.datetime(2026, 7, 5, 9, 0, tzinfo=dt.UTC)

    @patch(
        "ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_bot_joined_at_by_channel",
        return_value={},
    )
    @patch(
        "ee.billing.salesforce_enrichment.conversations_signals._fetch_last_customer_message_at_by_org",
        return_value={},
    )
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_trusted_slack_channel_activity_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_returns_latest_support_ticket_without_slack_rows(
        self,
        mock_fetch_rows,
        mock_fetch_channel_activity,
        mock_fetch_latest_tickets,
        _mock_fetch_last_customer,
        _mock_fetch_bot_joined,
    ):
        org_id = "org-1"
        mock_fetch_rows.return_value = []
        mock_fetch_channel_activity.return_value = []
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

    @patch(
        "ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_bot_joined_at_by_channel",
        return_value={},
    )
    @patch(
        "ee.billing.salesforce_enrichment.conversations_signals._fetch_last_customer_message_at_by_org",
        return_value={},
    )
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_latest_support_ticket_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_trusted_slack_channel_activity_rows")
    @patch("ee.billing.salesforce_enrichment.conversations_signals._fetch_slack_channel_aggregate_rows")
    def test_returns_empty_when_no_rows(
        self,
        mock_fetch_rows,
        mock_fetch_channel_activity,
        mock_fetch_latest_tickets,
        _mock_fetch_last_customer,
        _mock_fetch_bot_joined,
    ):
        mock_fetch_rows.return_value = []
        mock_fetch_channel_activity.return_value = []
        mock_fetch_latest_tickets.return_value = []

        result = aggregate_conversations_slack_signals_for_orgs(["org-1"], include_slack_user_count=False)

        assert result == {}

    @patch("ee.billing.salesforce_enrichment.conversations_signals.query_with_columns")
    def test_fetch_slack_bot_joined_at_keys_rows_by_workspace_and_channel(self, mock_query):
        # The ClickHouse driver can return naive datetimes; they must come back UTC-aware.
        # A row without a datetime value must be skipped, not crash or store None.
        mock_query.return_value = [
            {"slack_team_id": "T123", "slack_channel_id": "C1", "bot_joined_at": dt.datetime(2026, 7, 5, 9, 0)},
            {
                "slack_team_id": "T999",
                "slack_channel_id": "C2",
                "bot_joined_at": dt.datetime(2026, 7, 6, 10, 0, tzinfo=dt.UTC),
            },
            {"slack_team_id": "T000", "slack_channel_id": "C3", "bot_joined_at": None},
        ]

        result = _fetch_slack_bot_joined_at_by_channel(["C1", "C2"])

        assert result == {
            ("T123", "C1"): dt.datetime(2026, 7, 5, 9, 0, tzinfo=dt.UTC),
            ("T999", "C2"): dt.datetime(2026, 7, 6, 10, 0, tzinfo=dt.UTC),
        }

    @patch("ee.billing.salesforce_enrichment.conversations_signals.query_with_columns")
    def test_fetch_slack_bot_joined_at_skips_query_without_channels(self, mock_query):
        # An empty IN () clause is a ClickHouse syntax error, so the guard is load-bearing.
        assert _fetch_slack_bot_joined_at_by_channel([]) == {}
        mock_query.assert_not_called()

    @parameterized.expand(
        [
            ("workspace_match", "T123", "C1", dt.datetime(2026, 7, 5, 9, 0, tzinfo=dt.UTC)),
            ("workspace_mismatch", "T999", "C1", None),
            # Channel ids are only unique per workspace, so a workspace-less row is
            # never matched even when a channel id lines up.
            ("no_workspace", None, "C1", None),
            ("no_channel", "T123", None, None),
        ]
    )
    def test_lookup_slack_bot_joined_at(
        self, _name: str, slack_team_id: str | None, slack_channel_id: str | None, expected: dt.datetime | None
    ) -> None:
        joined_at_by_channel = {
            ("T123", "C1"): dt.datetime(2026, 7, 5, 9, 0, tzinfo=dt.UTC),
            ("T456", "C1"): dt.datetime(2026, 7, 4, 8, 0, tzinfo=dt.UTC),
        }

        assert _lookup_slack_bot_joined_at(joined_at_by_channel, slack_team_id, slack_channel_id) == expected

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
        team: Team | None = None,
    ) -> Ticket:
        return Ticket.objects.create_with_number(
            team=team or self.team,
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

    def _create_ticket_comment(
        self, ticket: Ticket, author_type: str, created_at: dt.datetime, deleted: bool = False
    ) -> Comment:
        comment = Comment.objects.create(
            team=ticket.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="message",
            item_context={"author_type": author_type, "is_private": False},
            deleted=deleted,
        )
        # created_at is auto_now_add, so backdate it after the fact.
        Comment.objects.filter(id=comment.id).update(created_at=created_at)
        return comment

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

    def test_employee_activity_updates_a_trusted_customer_channel(self):
        customer_activity = dt.datetime(2026, 6, 29, 10, 0, tzinfo=dt.UTC)
        other_channel_activity = dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC)
        employee_activity = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(channel_id="C_CUSTOMER", activity_at=customer_activity)
        most_recent_customer_ticket = self._create_slack_ticket(
            channel_id="C_OTHER", activity_at=other_channel_activity
        )

        employee_org, employee = self._create_member_of_other_org(f"employee-{uuid.uuid4()}@posthog.com")
        self._create_slack_ticket(
            org_id=str(employee_org.id),
            channel_id="C_CUSTOMER",
            activity_at=employee_activity,
            distinct_id=employee.distinct_id,
        )

        with self.settings(SITE_URL="https://us.posthog.com"):
            result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        signals = result[self.org_id]
        assert signals.slack_channel_url == "https://app.slack.com/client/T123/C_CUSTOMER"
        assert signals.last_slack_activity == employee_activity
        assert signals.slack_issue_count == 1
        assert (
            signals.most_recent_support_ticket_url
            == f"https://us.posthog.com/project/{self.team.id}/support/tickets/{most_recent_customer_ticket.ticket_number}"
        )

    def test_unverified_ticket_does_not_bump_trusted_channel_activity(self):
        verified_activity = dt.datetime(2026, 6, 29, 10, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(channel_id="C_CUSTOMER", activity_at=verified_activity)
        self._create_slack_ticket(
            channel_id="C_CUSTOMER",
            activity_at=dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC),
            distinct_id=f"stranger-{uuid.uuid4()}",
            identity_verified=False,
        )

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        assert result[self.org_id].last_slack_activity == verified_activity

    def test_trusted_activity_covers_all_teams_in_a_channel_group(self):
        second_team = Team.objects.create(organization=self.organization, name="second")
        newest_customer_activity = dt.datetime(2026, 6, 29, 10, 0, tzinfo=dt.UTC)
        employee_activity = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(channel_id="C_MULTI", activity_at=dt.datetime(2026, 6, 28, 10, 0, tzinfo=dt.UTC))
        self._create_slack_ticket(channel_id="C_MULTI", activity_at=newest_customer_activity, team=second_team)

        employee_org, employee = self._create_member_of_other_org(f"employee-{uuid.uuid4()}@posthog.com")
        self._create_slack_ticket(
            org_id=str(employee_org.id),
            channel_id="C_MULTI",
            activity_at=employee_activity,
            distinct_id=employee.distinct_id,
            team=second_team,
        )

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        assert result[self.org_id].last_slack_activity == employee_activity

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
        latest_activity = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(channel_id="C_SHARED", activity_at=latest_activity, slack_team_id="T_TWO")
        # A workspace-less row tied on recency must lose to the known-workspace row.
        self._create_slack_ticket(channel_id="C_SHARED", activity_at=latest_activity, slack_team_id=None)

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        signals = result[self.org_id]
        assert signals.slack_channel_url == "https://app.slack.com/client/T_TWO/C_SHARED"
        assert signals.slack_issue_count == 1

    def test_null_workspace_channel_activity_stays_scoped_to_its_org(self):
        own_activity = dt.datetime(2026, 6, 29, 12, 0, tzinfo=dt.UTC)
        self._create_slack_ticket(channel_id="C_OWN", activity_at=own_activity, slack_team_id=None)
        self._create_slack_ticket(
            channel_id="C_SHARED_ID",
            activity_at=dt.datetime(2026, 6, 29, 10, 0, tzinfo=dt.UTC),
            slack_team_id=None,
        )

        # Another org in the batch has a newer ticket in a different team whose
        # channel happens to reuse the same ID (channel IDs are only unique per
        # workspace, and here the workspace is unknown).
        other_org, other_user = self._create_member_of_other_org(f"other-{uuid.uuid4()}@posthog.com")
        other_team = Team.objects.create(organization=other_org, name="other")
        self._create_slack_ticket(
            org_id=str(other_org.id),
            channel_id="C_SHARED_ID",
            activity_at=dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC),
            slack_team_id=None,
            distinct_id=other_user.distinct_id,
            team=other_team,
        )

        alone = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)
        together = aggregate_conversations_slack_signals_for_orgs(
            [self.org_id, str(other_org.id)], include_slack_user_count=False
        )

        assert together[self.org_id] == alone[self.org_id]
        assert together[self.org_id].slack_channel_url == "https://app.slack.com/archives/C_OWN"
        assert together[self.org_id].last_slack_activity == own_activity

    def test_last_customer_message_at_counts_only_customer_comments_on_verified_tickets(self):
        slack_ticket = self._create_slack_ticket(
            channel_id="C123", activity_at=dt.datetime(2026, 6, 28, 10, 0, tzinfo=dt.UTC)
        )
        expected = dt.datetime(2026, 6, 29, 11, 0, tzinfo=dt.UTC)
        self._create_ticket_comment(slack_ticket, "customer", dt.datetime(2026, 6, 28, 10, 0, tzinfo=dt.UTC))
        # Staff, AI, and deleted-customer messages are all newer but must not count.
        self._create_ticket_comment(slack_ticket, "support", dt.datetime(2026, 6, 30, 9, 0, tzinfo=dt.UTC))
        self._create_ticket_comment(slack_ticket, "AI", dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC))
        self._create_ticket_comment(
            slack_ticket, "customer", dt.datetime(2026, 6, 30, 11, 0, tzinfo=dt.UTC), deleted=True
        )

        # The org-wide max spans channels: a newer customer message on an email ticket wins.
        email_ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=f"session-{uuid.uuid4()}",
            distinct_id="",
            channel_source=Channel.EMAIL,
            email_from=self.user.email,
            organization_id=self.org_id,
            last_message_at=expected,
            identity_verified=True,
        )
        self._create_ticket_comment(email_ticket, "customer", expected)

        # Customer messages on unverified tickets must not count.
        unverified_ticket = self._create_slack_ticket(
            channel_id="C_UNVERIFIED",
            activity_at=dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC),
            identity_verified=False,
        )
        self._create_ticket_comment(unverified_ticket, "customer", dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC))

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        assert result[self.org_id].last_customer_message_at == expected

    def test_last_customer_message_at_stays_scoped_per_org_within_a_batch(self):
        # Both orgs' teams land in the same batch-wide comment query, so attribution
        # must key on the ticket (item_id), not the team set — a regression here would
        # hand one org the other's newer timestamp.
        own_time = dt.datetime(2026, 6, 29, 10, 0, tzinfo=dt.UTC)
        own_ticket = self._create_slack_ticket(channel_id="C_OWN", activity_at=own_time)
        self._create_ticket_comment(own_ticket, "customer", own_time)

        other_org, other_user = self._create_member_of_other_org(f"other-{uuid.uuid4()}@posthog.com")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_time = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
        other_ticket = self._create_slack_ticket(
            org_id=str(other_org.id),
            channel_id="C_OTHER",
            activity_at=other_time,
            distinct_id=other_user.distinct_id,
            team=other_team,
        )
        self._create_ticket_comment(other_ticket, "customer", other_time)

        # A comment forged through the generic comments API — created under the other
        # org's team but pointing at this org's ticket — must not count either.
        forged = Comment.objects.create(
            team=other_team,
            scope="conversations_ticket",
            item_id=str(own_ticket.id),
            content="forged",
            item_context={"author_type": "customer", "is_private": False},
            deleted=False,
        )
        Comment.objects.filter(id=forged.id).update(created_at=dt.datetime(2026, 7, 1, 9, 0, tzinfo=dt.UTC))

        result = aggregate_conversations_slack_signals_for_orgs(
            [self.org_id, str(other_org.id)], include_slack_user_count=False
        )

        assert result[self.org_id].last_customer_message_at == own_time
        assert result[str(other_org.id)].last_customer_message_at == other_time

    def test_last_customer_message_at_is_none_without_customer_comments(self):
        ticket = self._create_slack_ticket(
            channel_id="C123", activity_at=dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC)
        )
        self._create_ticket_comment(ticket, "support", dt.datetime(2026, 6, 30, 10, 0, tzinfo=dt.UTC))

        result = aggregate_conversations_slack_signals_for_orgs([self.org_id], include_slack_user_count=False)

        assert result[self.org_id].last_customer_message_at is None

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
