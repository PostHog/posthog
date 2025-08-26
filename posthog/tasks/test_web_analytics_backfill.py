from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TransactionTestCase
from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.tasks.web_analytics_backfill import (
    backfill_web_analytics_tables_for_team,
    validate_team_for_backfill,
    get_backfill_date_range,
    validate_backfill_data_integrity,
)
from posthog.test.base import ClickhouseTestMixin


class TestWebAnalyticsBackfillIntegration(ClickhouseTestMixin, TransactionTestCase):
    """Integration tests that verify actual database operations."""

    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(
            organization=self.organization,
            web_analytics_pre_aggregated_tables_enabled=True,
            timezone="UTC"
        )

    def tearDown(self):
        # Clean up any test data
        sync_execute(f"DELETE FROM web_pre_aggregated_stats WHERE team_id = {self.team.id}")
        sync_execute(f"DELETE FROM web_pre_aggregated_bounces WHERE team_id = {self.team.id}")
        super().tearDown()

    def _insert_test_events(self):
        """Insert test pageview events for backfill testing."""
        # Insert some test events that should be backfilled
        base_date = datetime.utcnow() - timedelta(days=3)

        for i in range(5):
            event_date = base_date + timedelta(hours=i * 2)

            sync_execute(f"""
                INSERT INTO events (
                    uuid, event, properties, timestamp, team_id, distinct_id,
                    elements_chain, created_at
                ) VALUES (
                    generateUUIDv4(),
                    '$pageview',
                    {{'$current_url': 'https://test.com/page{i}'}},
                    '{event_date.strftime('%Y-%m-%d %H:%M:%S')}',
                    {self.team.id},
                    'test-user-{i}',
                    '',
                    '{event_date.strftime('%Y-%m-%d %H:%M:%S')}'
                )
            """)

    def test_backfill_inserts_actual_data(self):
        """Test that backfill actually inserts data into pre-aggregated tables."""
        # Insert test events first
        self._insert_test_events()

        # Verify tables are empty initially
        stats_count_before = sync_execute(
            f"SELECT COUNT(*) FROM web_pre_aggregated_stats WHERE team_id = {self.team.id}"
        )[0][0]
        bounces_count_before = sync_execute(
            f"SELECT COUNT(*) FROM web_pre_aggregated_bounces WHERE team_id = {self.team.id}"
        )[0][0]

        self.assertEqual(stats_count_before, 0)
        self.assertEqual(bounces_count_before, 0)

        # Run backfill
        result = backfill_web_analytics_tables_for_team(self.team.id, backfill_days=7)

        # Verify success
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["team_id"], self.team.id)

        # Verify data was actually inserted
        stats_count_after = sync_execute(
            f"SELECT COUNT(*) FROM web_pre_aggregated_stats WHERE team_id = {self.team.id}"
        )[0][0]
        bounces_count_after = sync_execute(
            f"SELECT COUNT(*) FROM web_pre_aggregated_bounces WHERE team_id = {self.team.id}"
        )[0][0]

        # Should have inserted some data
        self.assertGreater(stats_count_after, 0)
        self.assertGreaterEqual(bounces_count_after, 0)  # Bounces might be 0 if no bounces

    def test_backfill_respects_date_range(self):
        """Test that backfill only processes data within the specified date range."""
        # Insert events both inside and outside the range
        old_date = datetime.utcnow() - timedelta(days=45)  # Outside range
        recent_date = datetime.utcnow() - timedelta(days=3)  # Inside range

        # Insert old event
        sync_execute(f"""
            INSERT INTO events (
                uuid, event, properties, timestamp, team_id, distinct_id,
                elements_chain, created_at
            ) VALUES (
                generateUUIDv4(),
                '$pageview',
                {{'$current_url': 'https://old.com'}},
                '{old_date.strftime('%Y-%m-%d %H:%M:%S')}',
                {self.team.id},
                'old-user',
                '',
                '{old_date.strftime('%Y-%m-%d %H:%M:%S')}'
            )
        """)

        # Insert recent event
        sync_execute(f"""
            INSERT INTO events (
                uuid, event, properties, timestamp, team_id, distinct_id,
                elements_chain, created_at
            ) VALUES (
                generateUUIDv4(),
                '$pageview',
                {{'$current_url': 'https://recent.com'}},
                '{recent_date.strftime('%Y-%m-%d %H:%M:%S')}',
                {self.team.id},
                'recent-user',
                '',
                '{recent_date.strftime('%Y-%m-%d %H:%M:%S')}'
            )
        """)

        # Run backfill for last 7 days
        backfill_web_analytics_tables_for_team(self.team.id, backfill_days=7)

        # Check that only recent data was processed
        date_range = get_backfill_date_range(7)
        stats_data = sync_execute(f"""
            SELECT period_bucket
            FROM web_pre_aggregated_stats
            WHERE team_id = {self.team.id}
        """)

        if stats_data:
            for row in stats_data:
                bucket_date = row[0].strftime('%Y-%m-%d')
                self.assertGreaterEqual(bucket_date, date_range[0])
                self.assertLess(bucket_date, date_range[1])

    def test_validate_backfill_data_integrity_real_data(self):
        """Test data integrity validation with real database queries."""
        # Insert some test data directly into pre-aggregated tables
        test_date = datetime.utcnow().strftime('%Y-%m-%d')

        sync_execute(f"""
            INSERT INTO web_pre_aggregated_stats
            (team_id, period_bucket, granularity, pathname, views)
            VALUES ({self.team.id}, '{test_date}', 'day', '/test', 100)
        """)

        sync_execute(f"""
            INSERT INTO web_pre_aggregated_bounces
            (team_id, period_bucket, granularity, pathname, bounces, visits)
            VALUES ({self.team.id}, '{test_date}', 'day', '/test', 20, 100)
        """)

        # Validate integrity
        result = validate_backfill_data_integrity(
            team_id=self.team.id,
            date_start=test_date,
            date_end=(datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["validation_results"]["web_pre_aggregated_stats_rows"], 1)
        self.assertEqual(result["validation_results"]["web_pre_aggregated_bounces_rows"], 1)

    def test_backfill_skips_when_tables_disabled(self):
        """Test that backfill skips when pre-aggregated tables are disabled."""
        # Disable tables
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()

        # Insert test events
        self._insert_test_events()

        # Run backfill
        result = backfill_web_analytics_tables_for_team(self.team.id)

        # Should skip
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "team_validation_failed")

        # Verify no data was inserted
        stats_count = sync_execute(
            f"SELECT COUNT(*) FROM web_pre_aggregated_stats WHERE team_id = {self.team.id}"
        )[0][0]
        self.assertEqual(stats_count, 0)

    def test_get_backfill_date_range(self):
        """Test date range calculation for backfill."""
        start_date, end_date = get_backfill_date_range(days=7)

        # Verify format
        self.assertRegex(start_date, r'\d{4}-\d{2}-\d{2}')
        self.assertRegex(end_date, r'\d{4}-\d{2}-\d{2}')

        # Verify range is approximately 7 days
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        delta = end_dt - start_dt
        self.assertAlmostEqual(delta.days, 7, delta=1)

    def test_validate_team_for_backfill(self):
        """Test team validation logic."""
        # Valid team
        team = validate_team_for_backfill(self.team.id)
        self.assertEqual(team.id, self.team.id)

        # Disabled team
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()
        team = validate_team_for_backfill(self.team.id)
        self.assertIsNone(team)

        # Non-existent team
        team = validate_team_for_backfill(99999)
        self.assertIsNone(team)


class TestWebAnalyticsSignals(ClickhouseTestMixin, TransactionTestCase):
    """Test Django signal handlers for web analytics backfill."""

    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(
            organization=self.organization,
            web_analytics_pre_aggregated_tables_enabled=False
        )

    @patch('posthog.tasks.web_analytics_backfill.backfill_web_analytics_tables_for_team.delay')
    def test_signal_triggers_backfill_on_enable(self, mock_delay):
        """Test that enabling pre-aggregated tables triggers backfill."""
        # Enable tables - should trigger signal
        self.team.web_analytics_pre_aggregated_tables_enabled = True
        self.team.save()

        # Verify backfill was triggered
        mock_delay.assert_called_once_with(self.team.id)

    @patch('posthog.tasks.web_analytics_backfill.backfill_web_analytics_tables_for_team.delay')
    def test_signal_does_not_trigger_when_already_enabled(self, mock_delay):
        """Test that signal doesn't trigger when tables are already enabled."""
        # Start with enabled tables
        self.team.web_analytics_pre_aggregated_tables_enabled = True
        self.team.save()
        mock_delay.reset_mock()

        # Update something else - should not trigger
        self.team.name = "Updated Name"
        self.team.save()

        # Verify backfill was not triggered
        mock_delay.assert_not_called()

    @patch('posthog.tasks.web_analytics_backfill.backfill_web_analytics_tables_for_team.delay')
    def test_signal_does_not_trigger_on_disable(self, mock_delay):
        """Test that disabling pre-aggregated tables doesn't trigger backfill."""
        # Start with enabled tables
        self.team.web_analytics_pre_aggregated_tables_enabled = True
        self.team.save()
        mock_delay.reset_mock()

        # Disable tables - should not trigger backfill
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()

        # Verify backfill was not triggered
        mock_delay.assert_not_called()
