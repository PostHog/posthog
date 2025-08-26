from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TransactionTestCase
from posthog.models import Team
from posthog.tasks.scheduled_web_analytics_backfill import (
    get_backfill_date_range,
    get_teams_needing_backfill,
    check_team_has_recent_data,
    backfill_team,
    process_backfill_batch,
    discover_and_backfill_teams,
)
from posthog.test.base import ClickhouseTestMixin


class TestScheduledWebAnalyticsBackfill(ClickhouseTestMixin, TransactionTestCase):
    """Test scheduled web analytics backfill functionality."""

    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(
            organization=self.organization,
            web_analytics_pre_aggregated_tables_enabled=True,
            timezone="UTC"
        )

    def test_get_backfill_date_range(self):
        """Test date range calculation."""
        start_date, end_date = get_backfill_date_range(days=7)

        # Verify format
        self.assertRegex(start_date, r'\d{4}-\d{2}-\d{2}')
        self.assertRegex(end_date, r'\d{4}-\d{2}-\d{2}')

        # Verify range is approximately 7 days
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        delta = end_dt - start_dt
        self.assertAlmostEqual(delta.days, 7, delta=1)

    def test_get_teams_needing_backfill(self):
        """Test team discovery for backfill."""
        # Create additional teams
        Team.objects.create(
            organization=self.organization,
            web_analytics_pre_aggregated_tables_enabled=False  # Should be excluded
        )
        Team.objects.create(
            organization=self.organization,
            web_analytics_pre_aggregated_tables_enabled=True  # Should be included
        )

        teams = get_teams_needing_backfill(limit=10)

        # Should find teams with pre-aggregated tables enabled
        self.assertGreaterEqual(len(teams), 2)
        self.assertIn(self.team.id, teams)

    def test_check_team_has_recent_data(self):
        """Test checking for existing recent data."""
        date_start = (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%d')

        # Initially should have no data
        has_data = check_team_has_recent_data(self.team.id, date_start)
        self.assertFalse(has_data)

    @patch('posthog.tasks.scheduled_web_analytics_backfill.execute_backfill_query')
    @patch('posthog.tasks.scheduled_web_analytics_backfill.check_team_has_recent_data')
    def test_backfill_team_success(self, mock_check_data, mock_execute):
        """Test successful team backfill."""
        mock_check_data.return_value = False  # No recent data
        mock_execute.return_value = None  # Success

        result = backfill_team(self.team.id, backfill_days=7)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["team_id"], self.team.id)
        self.assertEqual(result["backfill_days"], 7)

        # Should call execute twice (stats and bounces tables)
        self.assertEqual(mock_execute.call_count, 2)

    @patch('posthog.tasks.scheduled_web_analytics_backfill.check_team_has_recent_data')
    def test_backfill_team_skips_with_recent_data(self, mock_check_data):
        """Test that backfill skips teams with recent data."""
        mock_check_data.return_value = True  # Has recent data

        result = backfill_team(self.team.id)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "has_recent_data")

    def test_backfill_team_skips_disabled_team(self):
        """Test that backfill skips teams without pre-aggregated tables."""
        # Disable pre-aggregated tables
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()

        result = backfill_team(self.team.id)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "team_not_eligible")

    @patch('posthog.tasks.scheduled_web_analytics_backfill.backfill_team')
    def test_process_backfill_batch(self, mock_backfill_team):
        """Test processing a batch of teams."""
        # Mock results
        mock_backfill_team.side_effect = [
            {"status": "completed", "team_id": 1},
            {"status": "skipped", "team_id": 2, "reason": "has_recent_data"},
            {"status": "failed", "team_id": 3, "error": "test error"},
        ]

        result = process_backfill_batch([1, 2, 3], backfill_days=7)

        self.assertEqual(result["status"], "batch_completed")
        self.assertEqual(result["total_teams"], 3)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 1)

    @patch('posthog.tasks.scheduled_web_analytics_backfill.get_teams_needing_backfill')
    @patch('posthog.tasks.scheduled_web_analytics_backfill.process_backfill_batch')
    def test_discover_and_backfill_teams(self, mock_process_batch, mock_get_teams):
        """Test the main discovery and backfill task."""
        mock_get_teams.return_value = [1, 2, 3]
        mock_process_batch.return_value = {
            "status": "batch_completed",
            "completed": 2,
            "skipped": 1,
            "failed": 0
        }

        result = discover_and_backfill_teams(7)

        self.assertEqual(result["status"], "batch_completed")
        mock_get_teams.assert_called_once_with(limit=5)  # BACKFILL_BATCH_SIZE
        mock_process_batch.assert_called_once_with([1, 2, 3], 7)

    @patch('posthog.tasks.scheduled_web_analytics_backfill.get_teams_needing_backfill')
    def test_discover_and_backfill_no_teams(self, mock_get_teams):
        """Test discovery when no teams need backfill."""
        mock_get_teams.return_value = []

        result = discover_and_backfill_teams()

        self.assertEqual(result["status"], "no_teams_found")

    def test_backfill_days_safety_limit(self):
        """Test that backfill days are limited to maximum."""
        # This would be tested in the actual task, but we can verify the constant
        from posthog.tasks.scheduled_web_analytics_backfill import MAX_BACKFILL_DAYS
        self.assertEqual(MAX_BACKFILL_DAYS, 30)


class TestWebAnalyticsBackfillManagementCommand(TransactionTestCase):
    """Test the management command functionality."""

    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(
            organization_id=1,  # Simple ID for testing
            web_analytics_pre_aggregated_tables_enabled=True
        )

    @patch('posthog.tasks.scheduled_web_analytics_backfill.backfill_team')
    def test_management_command_single_team(self, mock_backfill):
        """Test running the command for a single team."""
        from django.core.management import call_command
        from io import StringIO

        mock_backfill.return_value = {"status": "completed", "team_id": self.team.id}

        out = StringIO()
        call_command('run_web_analytics_backfill', '--team-id', str(self.team.id), stdout=out)

        output = out.getvalue()
        self.assertIn("Processing team", output)
        self.assertIn("completed", output)
        mock_backfill.assert_called_once_with(self.team.id, 7)

    @patch('posthog.tasks.scheduled_web_analytics_backfill.discover_and_backfill_teams')
    def test_management_command_discover_teams(self, mock_discover):
        """Test running the command to discover teams."""
        from django.core.management import call_command
        from io import StringIO

        mock_discover.return_value = {"status": "batch_completed", "completed": 2}

        out = StringIO()
        call_command('run_web_analytics_backfill', stdout=out)

        output = out.getvalue()
        self.assertIn("Discovering teams", output)
        mock_discover.assert_called_once_with(7)

    def test_management_command_dry_run(self):
        """Test dry run mode."""
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('run_web_analytics_backfill', '--dry-run', '--team-id', str(self.team.id), stdout=out)

        output = out.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn(f"Would backfill team {self.team.id}", output)

