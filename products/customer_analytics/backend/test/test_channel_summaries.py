from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.logic.channel_summaries import get_last_closed_period
from products.customer_analytics.backend.models import Account, AccountChannelSummary
from products.customer_analytics.backend.test.factories import create_account

SP = ZoneInfo("America/Sao_Paulo")


class TestGetLastClosedPeriod:
    @parameterized.expand(
        [
            (
                "daily",
                "daily",
                datetime(2026, 7, 28, 15, 30, tzinfo=UTC),
                datetime(2026, 7, 27, 0, 0, tzinfo=SP),
                datetime(2026, 7, 28, 0, 0, tzinfo=SP),
            ),
            (
                # 2026-07-28 is a Tuesday; last ISO week runs Mon 20th to Mon 27th.
                "weekly",
                "weekly",
                datetime(2026, 7, 28, 15, 30, tzinfo=UTC),
                datetime(2026, 7, 20, 0, 0, tzinfo=SP),
                datetime(2026, 7, 27, 0, 0, tzinfo=SP),
            ),
            (
                "monthly",
                "monthly",
                datetime(2026, 7, 28, 15, 30, tzinfo=UTC),
                datetime(2026, 6, 1, 0, 0, tzinfo=SP),
                datetime(2026, 7, 1, 0, 0, tzinfo=SP),
            ),
            (
                # 01:30 UTC on Aug 1 is still Jul 31 in São Paulo, so "yesterday" is Jul 30.
                "daily_tz_shifts_the_date",
                "daily",
                datetime(2026, 8, 1, 1, 30, tzinfo=UTC),
                datetime(2026, 7, 30, 0, 0, tzinfo=SP),
                datetime(2026, 7, 31, 0, 0, tzinfo=SP),
            ),
            (
                "monthly_across_year_boundary",
                "monthly",
                datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
                datetime(2025, 12, 1, 0, 0, tzinfo=SP),
                datetime(2026, 1, 1, 0, 0, tzinfo=SP),
            ),
        ]
    )
    def test_closed_periods(self, _name, cadence, now, expected_start, expected_end):
        start, end = get_last_closed_period(cadence, now, SP)

        assert start == expected_start
        assert end == expected_end


class TestListAccountsDueForSlackSummary(BaseTest):
    NOW = datetime(2026, 7, 28, 15, 30, tzinfo=UTC)

    def _opted_in_account(self, **kwargs) -> Account:
        defaults = {
            "team_id": self.team.id,
            "slack_summary_cadence": "daily",
            "_properties": {"slack_channel_id": "C123"},
        }
        return create_account(**{**defaults, **kwargs})

    def test_returns_due_account_with_periods_in_team_timezone(self):
        self.team.timezone = "America/Sao_Paulo"
        self.team.save()
        account = self._opted_in_account()

        due = facade.list_accounts_due_for_slack_summary(now=self.NOW)

        assert [d.account_id for d in due] == [str(account.id)]
        assert due[0].slack_channel_id == "C123"
        assert due[0].cadence == "daily"
        assert due[0].period_start == datetime(2026, 7, 27, 0, 0, tzinfo=SP)
        assert due[0].period_end == datetime(2026, 7, 28, 0, 0, tzinfo=SP)

    @parameterized.expand(
        [
            ("no_cadence", {"slack_summary_cadence": None}),
            ("no_channel_bound", {"_properties": {}}),
        ]
    )
    def test_skips_accounts_not_opted_in_or_unbound(self, _name, overrides):
        self._opted_in_account(**overrides)

        assert facade.list_accounts_due_for_slack_summary(now=self.NOW) == []

    def test_period_with_existing_summary_is_not_due_again(self):
        account = self._opted_in_account()
        period_start, period_end = get_last_closed_period("daily", self.NOW, ZoneInfo("UTC"))
        facade.record_channel_summary(
            team_id=self.team.id,
            account_id=str(account.id),
            slack_channel_id="C123",
            cadence="daily",
            period_start=period_start,
            period_end=period_end,
            content="summary",
            message_count=3,
        )

        assert facade.list_accounts_due_for_slack_summary(now=self.NOW) == []

    def test_summary_for_another_cadence_does_not_satisfy_the_period(self):
        account = self._opted_in_account(slack_summary_cadence="monthly")
        period_start, period_end = get_last_closed_period("monthly", self.NOW, ZoneInfo("UTC"))
        AccountChannelSummary.objects.unscoped().create(
            team_id=self.team.id,
            account_id=account.id,
            slack_channel_id="C123",
            cadence="weekly",
            period_start=period_start,
            period_end=period_end,
            content="other cadence",
        )

        due = facade.list_accounts_due_for_slack_summary(now=self.NOW)

        assert [d.cadence for d in due] == ["monthly"]


class TestRecordChannelSummary(BaseTest):
    def _record(self, account, **overrides) -> str | None:
        kwargs = {
            "team_id": self.team.id,
            "account_id": str(account.id),
            "slack_channel_id": "C123",
            "cadence": "daily",
            "period_start": datetime(2026, 7, 27, tzinfo=UTC),
            "period_end": datetime(2026, 7, 28, tzinfo=UTC),
            "content": "summary",
            "message_count": 3,
            "model_name": "claude-sonnet-5",
        }
        return facade.record_channel_summary(**{**kwargs, **overrides})

    def test_persists_message_metadata(self):
        account = create_account(team_id=self.team.id)
        refs = [{"author": "alice", "sent_at": "2026-07-27T10:00:00+00:00", "permalink": "https://slack/1"}]

        summary_id = self._record(account, messages=refs)

        assert summary_id is not None
        summary = AccountChannelSummary.objects.unscoped().get(id=summary_id)
        assert summary.messages == refs

    def test_duplicate_write_resolves_to_the_existing_row(self):
        account = create_account(team_id=self.team.id)

        first = self._record(account)
        second = self._record(account, content="retry content")

        assert first == second
        assert AccountChannelSummary.objects.unscoped().filter(account_id=account.id).count() == 1

    def test_returns_none_for_missing_account(self):
        account = create_account(team_id=self.team.id)
        account_id = str(account.id)
        account.delete()

        result = self._record(Account(id=account_id))

        assert result is None
        assert AccountChannelSummary.objects.unscoped().count() == 0


class TestAccountSummariesEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, name="Acme Corp")
        self.endpoint = f"/api/environments/{self.team.id}/accounts/{self.account.id}/summaries/"

    def _create_summary(self, period_start: datetime, cadence: str = "daily") -> AccountChannelSummary:
        return AccountChannelSummary.objects.unscoped().create(
            team_id=self.team.id,
            account_id=self.account.id,
            slack_channel_id="C123",
            cadence=cadence,
            period_start=period_start,
            period_end=period_start,
            content=f"summary for {period_start.date()}",
            message_count=1,
            messages=[{"author": "alice", "sent_at": "2026-07-25T10:00:00+00:00", "permalink": "https://slack/1"}],
        )

    def test_lists_summaries_newest_period_first_paginated(self):
        older = self._create_summary(datetime(2026, 7, 25, tzinfo=UTC))
        newer = self._create_summary(datetime(2026, 7, 27, tzinfo=UTC))

        response = self.client.get(self.endpoint)

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["count"] == 2
        assert [row["id"] for row in data["results"]] == [str(newer.id), str(older.id)]
        assert data["results"][0]["content"] == "summary for 2026-07-27"
        assert data["results"][0]["cadence"] == "daily"
        assert data["results"][0]["messages"] == [
            {"author": "alice", "sent_at": "2026-07-25T10:00:00+00:00", "permalink": "https://slack/1"}
        ]

    def test_other_teams_account_is_404(self):
        other_team = Team.objects.create(organization=self.organization)
        other_account = create_account(team_id=other_team.id)

        response = self.client.get(f"/api/environments/{self.team.id}/accounts/{other_account.id}/summaries/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cadence_set_and_cleared_through_account_update(self):
        detail = f"/api/environments/{self.team.id}/accounts/{self.account.id}/"

        response = self.client.patch(detail, {"slack_summary_cadence": "weekly"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["slack_summary_cadence"] == "weekly"
        self.account.refresh_from_db()
        assert self.account.slack_summary_cadence == "weekly"

        # A PATCH that doesn't mention the field must leave it untouched.
        response = self.client.patch(detail, {"name": "Acme"}, format="json")
        self.account.refresh_from_db()
        assert self.account.slack_summary_cadence == "weekly"

        response = self.client.patch(detail, {"slack_summary_cadence": None}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.account.refresh_from_db()
        assert self.account.slack_summary_cadence is None

    def test_invalid_cadence_is_rejected(self):
        response = self.client.patch(
            f"/api/environments/{self.team.id}/accounts/{self.account.id}/",
            {"slack_summary_cadence": "yearly"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
