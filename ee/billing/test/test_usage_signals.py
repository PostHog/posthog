from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import TestCase

from posthog.models import Dashboard, Insight, Organization, OrganizationMembership, Team, User

from ee.billing.salesforce_enrichment.usage_signals import (
    TeamUsageSignals,
    UsageSignals,
    aggregate_teams_to_org,
    aggregate_usage_signals_for_orgs,
    calc_momentum,
    get_org_dashboards_count,
    get_org_insights_count,
    get_org_login_recency,
    get_team_ids_for_orgs,
    get_teams_with_recordings_in_period,
    get_teams_with_usage_signals_in_period,
)


class TestCalcMomentum(TestCase):
    def test_positive_momentum(self):
        result = calc_momentum(current=150, previous=100)
        assert result == 50.0

    def test_negative_momentum(self):
        result = calc_momentum(current=50, previous=100)
        assert result == -50.0

    def test_zero_momentum(self):
        result = calc_momentum(current=100, previous=100)
        assert result == 0.0

    def test_previous_zero_returns_none(self):
        result = calc_momentum(current=100, previous=0)
        assert result is None

    def test_both_zero_returns_none(self):
        result = calc_momentum(current=0, previous=0)
        assert result is None

    def test_large_increase(self):
        result = calc_momentum(current=1000, previous=10)
        assert result == 9900.0

    def test_decimal_values(self):
        result = calc_momentum(current=1.5, previous=1.0)
        assert result == 50.0


class TestAggregateTeamsToOrg(TestCase):
    def test_single_team(self):
        team_signals = [
            TeamUsageSignals(
                team_id=1,
                active_persons=100,
                active_distinct_ids=90,
                session_count=50,
                total_events=1000,
                has_feature_flags=True,
                has_surveys=False,
                has_error_tracking=True,
                has_ai=False,
            )
        ]

        result = aggregate_teams_to_org(team_signals)

        assert result.active_users == 100
        assert result.sessions == 50
        assert result.total_events == 1000
        assert "feature_flags" in result.products_activated
        assert "error_tracking" in result.products_activated
        assert "surveys" not in result.products_activated

    def test_multiple_teams_sum(self):
        team_signals = [
            TeamUsageSignals(
                team_id=1,
                active_persons=100,
                active_distinct_ids=90,
                session_count=50,
                total_events=1000,
                has_feature_flags=True,
                has_surveys=False,
                has_error_tracking=False,
                has_ai=False,
            ),
            TeamUsageSignals(
                team_id=2,
                active_persons=200,
                active_distinct_ids=180,
                session_count=100,
                total_events=2000,
                has_feature_flags=False,
                has_surveys=True,
                has_error_tracking=False,
                has_ai=True,
            ),
        ]

        result = aggregate_teams_to_org(team_signals)

        assert result.active_users == 300  # 100 + 200
        assert result.sessions == 150  # 50 + 100
        assert result.total_events == 3000  # 1000 + 2000
        # Products are OR'd across teams
        assert "feature_flags" in result.products_activated
        assert "surveys" in result.products_activated
        assert "ai" in result.products_activated

    def test_empty_teams_list(self):
        result = aggregate_teams_to_org([])

        assert result.active_users == 0
        assert result.sessions == 0
        assert result.total_events == 0
        assert result.products_activated == []

    def test_events_per_session_calculation(self):
        team_signals = [
            TeamUsageSignals(
                team_id=1,
                active_persons=100,
                active_distinct_ids=90,
                session_count=50,
                total_events=500,
                has_feature_flags=False,
                has_surveys=False,
                has_error_tracking=False,
                has_ai=False,
            ),
            TeamUsageSignals(
                team_id=2,
                active_persons=100,
                active_distinct_ids=90,
                session_count=50,
                total_events=500,
                has_feature_flags=False,
                has_surveys=False,
                has_error_tracking=False,
                has_ai=False,
            ),
        ]

        result = aggregate_teams_to_org(team_signals)

        # 1000 events / 100 sessions = 10 events per session
        assert result.events_per_session == 10.0

    def test_zero_sessions_no_division_error(self):
        team_signals = [
            TeamUsageSignals(
                team_id=1,
                active_persons=100,
                active_distinct_ids=90,
                session_count=0,
                total_events=1000,
                has_feature_flags=False,
                has_surveys=False,
                has_error_tracking=False,
                has_ai=False,
            )
        ]

        result = aggregate_teams_to_org(team_signals)

        assert result.events_per_session is None


class TestOrgLoginRecency(TestCase):
    org: Organization
    team: Team

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.org, name="Test Team")

    def test_recent_login(self):
        user = User.objects.create(email="test@example.com")
        OrganizationMembership.objects.create(organization=self.org, user=user)
        user.last_login = datetime.now(tz=UTC) - timedelta(days=3)
        user.save()

        result = get_org_login_recency([str(self.org.id)])

        assert str(self.org.id) in result
        # Allow 1 day tolerance for test timing
        days = result[str(self.org.id)]
        assert days is not None and 2 <= days <= 4

    def test_no_login_returns_none(self):
        user = User.objects.create(email="nologin@example.com")
        OrganizationMembership.objects.create(organization=self.org, user=user)
        user.last_login = None
        user.save()

        result = get_org_login_recency([str(self.org.id)])

        # Org with no logins should either not be in result or have None
        if str(self.org.id) in result:
            assert result[str(self.org.id)] is None

    def test_multiple_users_returns_most_recent(self):
        user1 = User.objects.create(email="user1@example.com")
        user2 = User.objects.create(email="user2@example.com")
        OrganizationMembership.objects.create(organization=self.org, user=user1)
        OrganizationMembership.objects.create(organization=self.org, user=user2)

        user1.last_login = datetime.now(tz=UTC) - timedelta(days=10)
        user1.save()
        user2.last_login = datetime.now(tz=UTC) - timedelta(days=2)
        user2.save()

        result = get_org_login_recency([str(self.org.id)])

        # Should return 2 days (most recent), not 10
        assert str(self.org.id) in result
        days = result[str(self.org.id)]
        assert days is not None and 1 <= days <= 3


class TestOrgDashboardsCount(TestCase):
    org: Organization
    team: Team

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.org, name="Test Team")

    def test_counts_dashboards_in_period(self):
        now = datetime.now(tz=UTC)
        period_start = now - timedelta(days=7)
        period_end = now + timedelta(days=1)  # Include today

        # Create dashboards (created_at is auto_now_add, so they get today's date)
        Dashboard.objects.create(team=self.team, name="Dashboard 1")
        Dashboard.objects.create(team=self.team, name="Dashboard 2")

        result = get_org_dashboards_count([str(self.org.id)], period_start, period_end)

        assert result[str(self.org.id)] == 2

    def test_excludes_dashboards_outside_period(self):
        now = datetime.now(tz=UTC)
        period_start = now - timedelta(days=7)
        period_end = now + timedelta(days=1)

        # Create dashboards then update one to be outside the period
        old_dashboard = Dashboard.objects.create(team=self.team, name="Old Dashboard")
        Dashboard.objects.filter(id=old_dashboard.id).update(created_at=now - timedelta(days=30))

        # Dashboard in period (uses auto_now_add)
        Dashboard.objects.create(team=self.team, name="Recent Dashboard")

        result = get_org_dashboards_count([str(self.org.id)], period_start, period_end)

        assert result[str(self.org.id)] == 1

    def test_excludes_deleted_dashboards(self):
        now = datetime.now(tz=UTC)
        period_start = now - timedelta(days=7)
        period_end = now + timedelta(days=1)

        Dashboard.objects.create(team=self.team, name="Active Dashboard", deleted=False)
        Dashboard.objects.create(team=self.team, name="Deleted Dashboard", deleted=True)

        result = get_org_dashboards_count([str(self.org.id)], period_start, period_end)

        assert result[str(self.org.id)] == 1


class TestOrgInsightsCount(TestCase):
    org: Organization
    team: Team

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.org, name="Test Team")

    def test_counts_insights_in_period(self):
        now = datetime.now(tz=UTC)
        period_start = now - timedelta(days=7)
        period_end = now + timedelta(days=1)  # Include today

        # Create insights (created_at is auto_now_add, so they get today's date)
        Insight.objects.create(team=self.team, name="Insight 1")
        Insight.objects.create(team=self.team, name="Insight 2")

        result = get_org_insights_count([str(self.org.id)], period_start, period_end)

        assert result[str(self.org.id)] == 2

    def test_excludes_deleted_insights(self):
        now = datetime.now(tz=UTC)
        period_start = now - timedelta(days=7)
        period_end = now + timedelta(days=1)

        Insight.objects.create(team=self.team, name="Active Insight", deleted=False)
        Insight.objects.create(team=self.team, name="Deleted Insight", deleted=True)

        result = get_org_insights_count([str(self.org.id)], period_start, period_end)

        assert result[str(self.org.id)] == 1


class TestUsageSignalsDataClass(TestCase):
    def test_default_values(self):
        signals = UsageSignals()

        assert signals.active_users_7d == 0
        assert signals.active_users_30d == 0
        assert signals.sessions_7d == 0
        assert signals.events_per_session_7d is None
        assert signals.products_activated_7d == []
        assert signals.days_since_last_login is None
        assert signals.active_users_7d_momentum is None

    def test_with_values(self):
        signals = UsageSignals(
            active_users_7d=100,
            active_users_30d=500,
            sessions_7d=200,
            sessions_30d=800,
            events_per_session_7d=10.5,
            events_per_session_30d=9.8,
            insights_per_user_7d=2.5,
            dashboards_per_user_7d=1.0,
            products_activated_7d=["analytics", "recordings"],
            days_since_last_login=3,
            active_users_7d_momentum=15.5,
            sessions_7d_momentum=-5.0,
        )

        assert signals.active_users_7d == 100
        assert signals.sessions_7d == 200
        assert signals.events_per_session_7d == 10.5
        assert signals.products_activated_7d == ["analytics", "recordings"]
        assert signals.days_since_last_login == 3
        assert signals.active_users_7d_momentum == 15.5
        assert signals.sessions_7d_momentum == -5.0


class TestTeamUsageSignalsDataClass(TestCase):
    def test_default_values(self):
        signals = TeamUsageSignals(team_id=1)

        assert signals.team_id == 1
        assert signals.active_persons == 0
        assert signals.session_count == 0
        assert signals.has_feature_flags is False
        assert signals.has_ai is False

    def test_with_values(self):
        signals = TeamUsageSignals(
            team_id=42,
            active_persons=100,
            active_distinct_ids=95,
            session_count=200,
            total_events=5000,
            has_feature_flags=True,
            has_surveys=True,
            has_error_tracking=False,
            has_ai=True,
        )

        assert signals.team_id == 42
        assert signals.active_persons == 100
        assert signals.has_feature_flags is True
        assert signals.has_ai is True


class TestGetTeamIdsForOrgs(TestCase):
    org1: Organization
    org2: Organization
    org_no_teams: Organization
    team1: Team
    team2: Team
    team3: Team

    @classmethod
    def setUpTestData(cls):
        cls.org1 = Organization.objects.create(name="Test Org 1")
        cls.org2 = Organization.objects.create(name="Test Org 2")
        cls.org_no_teams = Organization.objects.create(name="Empty Org")
        cls.team1 = Team.objects.create(organization=cls.org1, name="Team 1")
        cls.team2 = Team.objects.create(organization=cls.org1, name="Team 2")
        cls.team3 = Team.objects.create(organization=cls.org2, name="Team 3")

    def test_returns_correct_mapping(self):
        result = get_team_ids_for_orgs([str(self.org1.id), str(self.org2.id)])

        assert str(self.org1.id) in result
        assert str(self.org2.id) in result
        assert set(result[str(self.org1.id)]) == {self.team1.id, self.team2.id}
        assert result[str(self.org2.id)] == [self.team3.id]

    def test_org_with_no_teams_returns_empty_list(self):
        result = get_team_ids_for_orgs([str(self.org_no_teams.id)])

        assert str(self.org_no_teams.id) in result
        assert result[str(self.org_no_teams.id)] == []

    def test_empty_org_ids_returns_empty_dict(self):
        result = get_team_ids_for_orgs([])

        assert result == {}

    def test_nonexistent_org_id_returns_empty_list(self):
        fake_org_id = "00000000-0000-0000-0000-000000000000"
        result = get_team_ids_for_orgs([fake_org_id])

        assert fake_org_id in result
        assert result[fake_org_id] == []


class TestGetTeamsWithUsageSignalsInPeriod(TestCase):
    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_returns_team_usage_signals(self, mock_sync_execute):
        mock_sync_execute.return_value = [
            (1, 100, 90, 50, 1000, True, False, True, False),
            (2, 200, 180, 100, 2000, False, True, False, True),
        ]

        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_usage_signals_in_period(begin, end, [1, 2])

        assert len(result) == 2
        assert result[0].team_id == 1
        assert result[0].active_persons == 100
        assert result[0].session_count == 50
        assert result[0].has_feature_flags is True
        assert result[0].has_error_tracking is True
        assert result[1].team_id == 2
        assert result[1].active_persons == 200
        assert result[1].has_surveys is True
        assert result[1].has_ai is True

    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_empty_team_ids_returns_empty_list(self, mock_sync_execute):
        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_usage_signals_in_period(begin, end, [])

        assert result == []
        mock_sync_execute.assert_not_called()

    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_no_results_returns_empty_list(self, mock_sync_execute):
        mock_sync_execute.return_value = []

        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_usage_signals_in_period(begin, end, [999])

        assert result == []


class TestGetTeamsWithRecordingsInPeriod(TestCase):
    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_returns_recording_counts(self, mock_sync_execute):
        mock_sync_execute.return_value = [(1, 50), (2, 100)]

        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_recordings_in_period(begin, end, [1, 2])

        assert result == {1: 50, 2: 100}

    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_empty_team_ids_returns_empty_dict(self, mock_sync_execute):
        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_recordings_in_period(begin, end, [])

        assert result == {}
        mock_sync_execute.assert_not_called()

    @patch("ee.billing.salesforce_enrichment.usage_signals.sync_execute")
    def test_no_recordings_returns_empty_dict(self, mock_sync_execute):
        mock_sync_execute.return_value = []

        begin = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 8, tzinfo=UTC)

        result = get_teams_with_recordings_in_period(begin, end, [1])

        assert result == {}


class TestAggregateUsageSignalsForOrgs(TestCase):
    org: Organization
    team: Team

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.org, name="Test Team")

    def test_empty_org_ids_returns_empty_dict(self):
        result = aggregate_usage_signals_for_orgs([])
        assert result == {}

    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_login_recency")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_teams_with_recordings_in_period")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_teams_with_usage_signals_in_period")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_insights_count")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_dashboards_count")
    def test_org_with_no_teams_returns_empty_signals(
        self,
        mock_dashboards,
        mock_insights,
        mock_usage_signals,
        mock_recordings,
        mock_login_recency,
    ):
        org_no_teams = Organization.objects.create(name="Empty Org")

        mock_dashboards.return_value = {}
        mock_insights.return_value = {}
        mock_usage_signals.return_value = []
        mock_recordings.return_value = {}
        mock_login_recency.return_value = {}

        result = aggregate_usage_signals_for_orgs([str(org_no_teams.id)])

        assert str(org_no_teams.id) in result
        signals = result[str(org_no_teams.id)]
        assert signals.active_users_7d == 0
        assert signals.sessions_7d == 0

    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_login_recency")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_teams_with_recordings_in_period")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_teams_with_usage_signals_in_period")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_insights_count")
    @patch("ee.billing.salesforce_enrichment.usage_signals.get_org_dashboards_count")
    def test_integrates_all_data_sources(
        self,
        mock_dashboards,
        mock_insights,
        mock_usage_signals,
        mock_recordings,
        mock_login_recency,
    ):
        org_id = str(self.org.id)
        team_id = self.team.id

        mock_dashboards.return_value = {org_id: 5}
        mock_insights.return_value = {org_id: 10}
        mock_usage_signals.return_value = [
            TeamUsageSignals(
                team_id=team_id,
                active_persons=100,
                active_distinct_ids=90,
                session_count=50,
                total_events=1000,
                has_feature_flags=True,
                has_surveys=False,
                has_error_tracking=False,
                has_ai=False,
            )
        ]
        mock_recordings.return_value = {team_id: 25}
        mock_login_recency.return_value = {org_id: 3}

        result = aggregate_usage_signals_for_orgs([org_id])

        assert org_id in result
        signals = result[org_id]
        assert signals.active_users_7d == 100
        assert signals.sessions_7d == 50
        assert signals.days_since_last_login == 3
        assert "feature_flags" in signals.products_activated_7d
        assert "recordings" in signals.products_activated_7d
