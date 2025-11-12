"""
Tests for team metadata HyperCache functionality.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.storage.team_metadata_cache import (
    TEAM_METADATA_BATCH_REFRESH_COUNTER,
    TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM,
    TEAM_METADATA_CACHE_COVERAGE_GAUGE,
    TEAM_METADATA_FIELDS,
    TEAM_METADATA_TEAMS_PROCESSED_COUNTER,
    clear_team_metadata_cache,
    get_team_metadata,
    get_teams_with_expiring_caches,
    update_team_metadata_cache,
)
from posthog.tasks.team_metadata import refresh_expiring_team_metadata_cache_entries, update_team_metadata_cache_task


class TestTeamMetadataCache(BaseTest):
    """Test basic team metadata cache functionality."""

    def test_get_and_update_team_metadata(self):
        """Test basic cache read and write operations."""
        # Clear cache to start fresh
        clear_team_metadata_cache(self.team)

        # Update cache
        success = update_team_metadata_cache(self.team)
        self.assertTrue(success)

        # Get from cache
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)
        assert metadata is not None  # Type narrowing for mypy
        self.assertEqual(metadata["id"], self.team.id)
        self.assertEqual(metadata["name"], self.team.name)

        # Verify all required fields are present
        for field in TEAM_METADATA_FIELDS:
            self.assertIn(field, metadata)

    def test_clear_cache(self):
        """Test clearing the cache."""
        # First populate cache
        update_team_metadata_cache(self.team)

        # Verify it's cached
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

        # Clear and verify it still works (will reload from DB)
        clear_team_metadata_cache(self.team)
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

    def test_cache_with_different_key_types(self):
        """Test that cache works with team ID and API token."""
        update_team_metadata_cache(self.team)

        # Get by team object
        metadata1 = get_team_metadata(self.team)

        # Get by team ID
        metadata2 = get_team_metadata(self.team.id)

        # Get by API token
        metadata3 = get_team_metadata(self.team.api_token)

        # All should return the same data
        self.assertIsNotNone(metadata1)
        self.assertIsNotNone(metadata2)
        self.assertIsNotNone(metadata3)
        assert metadata1 is not None  # Type narrowing for mypy
        assert metadata2 is not None  # Type narrowing for mypy
        assert metadata3 is not None  # Type narrowing for mypy
        self.assertEqual(metadata1["id"], metadata2["id"])
        self.assertEqual(metadata2["id"], metadata3["id"])


class TestTeamMetadataCacheTasks(TransactionTestCase):
    """Test Celery tasks for team metadata cache."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache")
    def test_update_task(self, mock_update):
        """Test the update task calls the cache update function."""
        mock_update.return_value = True

        update_team_metadata_cache_task(self.team.id)

        # Verify the cache update was called with the right team
        self.assertEqual(mock_update.call_count, 1)
        called_team = mock_update.call_args[0][0]
        self.assertEqual(called_team.id, self.team.id)

    def test_update_task_nonexistent_team(self):
        """Test task handles non-existent team gracefully."""
        # Should not raise an exception
        update_team_metadata_cache_task(999999)


class TestTeamMetadataCacheSignals(TransactionTestCase):
    """Test Django signals for cache updates."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    def test_team_save_triggers_update(self, mock_task):
        """Test that saving a team schedules a cache update."""
        team = Team.objects.create(
            organization=self.organization,
            name="New Team",
        )

        # Task should be called with the team ID
        mock_task.assert_called_once_with(team.id)

    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache")
    def test_team_delete_clears_cache(self, mock_clear):
        """Test that deleting a team clears its cache."""
        team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )

        team.delete()

        # Cache should be cleared
        mock_clear.assert_called_once()


class TestCacheStats(BaseTest):
    """Test cache statistics functionality."""

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_get_cache_stats_basic(self, mock_get_client):
        """Test basic cache stats gathering."""
        from posthog.storage.team_metadata_cache import get_cache_stats

        # Mock Redis client
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            b"cache:team_metadata:key1",
            b"cache:team_metadata:key2",
        ]
        mock_redis.ttl.side_effect = [3600, 86400]  # 1 hour, 1 day
        mock_redis.memory_usage.side_effect = [1024, 2048]  # Sample memory sizes in bytes

        with patch("posthog.models.team.team.Team.objects.count", return_value=5):
            stats = get_cache_stats()

        self.assertEqual(stats["total_cached"], 2)
        self.assertEqual(stats["total_teams"], 5)
        self.assertEqual(stats["ttl_distribution"]["expires_1h"], 1)
        self.assertEqual(stats["ttl_distribution"]["expires_24h"], 1)


class TestGetTeamsWithExpiringCaches(TransactionTestCase):
    """Test get_teams_with_expiring_caches functionality."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_returns_teams_with_expiring_ttl(self, mock_get_client):
        """Teams with TTL < threshold should be returned."""
        team1 = Team.objects.create(
            organization=self.organization,
            name="Team 1",
            ingested_event=True,
        )
        team2 = Team.objects.create(
            organization=self.organization,
            name="Team 2",
            ingested_event=True,
        )

        # Mock Redis to return keys with low TTL
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            f"cache/team_tokens/{team1.api_token}/team_metadata/full_metadata.json".encode(),
            f"cache/team_tokens/{team2.api_token}/team_metadata/full_metadata.json".encode(),
        ]
        mock_redis.ttl.return_value = 3600  # 1 hour (expiring soon)

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        # Both teams have expiring caches
        self.assertEqual(len(result), 2)
        self.assertIn(team1, result)
        self.assertIn(team2, result)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_skips_teams_with_fresh_ttl(self, mock_get_client):
        """Teams with TTL > threshold should not be returned."""
        team = Team.objects.create(
            organization=self.organization,
            name="Team",
            ingested_event=True,
        )

        # Mock Redis to return key with high TTL
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            f"cache/team_tokens/{team.api_token}/team_metadata/full_metadata.json".encode(),
        ]
        mock_redis.ttl.return_value = 5 * 24 * 3600  # 5 days (fresh)

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        # Team has fresh cache
        self.assertEqual(len(result), 0)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_returns_empty_when_no_expiring_caches(self, mock_get_client):
        """Should return empty list when no caches are expiring."""
        # Mock Redis to return no keys
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = []

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        self.assertEqual(len(result), 0)


class TestTeamMetadataCacheBatchMetrics(BaseTest):
    """Test Prometheus metrics for batch refresh job."""

    def test_batch_refresh_metrics(self):
        """Test that batch refresh updates all expected metrics."""
        update_team_metadata_cache(self.team)

        before_counter = TEAM_METADATA_BATCH_REFRESH_COUNTER.labels(result="success")._value.get()
        before_teams_success = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="success")._value.get()
        before_teams_failed = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="failed")._value.get()

        refresh_expiring_team_metadata_cache_entries()

        after_counter = TEAM_METADATA_BATCH_REFRESH_COUNTER.labels(result="success")._value.get()
        after_teams_success = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="success")._value.get()
        after_teams_failed = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="failed")._value.get()

        self.assertEqual(after_counter - before_counter, 1)
        self.assertGreaterEqual(after_teams_success - before_teams_success, 0)
        self.assertEqual(after_teams_failed - before_teams_failed, 0)

        histogram_samples = list(TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM._samples())
        self.assertGreater(len(histogram_samples), 0)

    def test_cache_coverage_gauge_updated(self):
        """Test that cache coverage gauge is updated after refresh."""
        update_team_metadata_cache(self.team)

        refresh_expiring_team_metadata_cache_entries()

        coverage = TEAM_METADATA_CACHE_COVERAGE_GAUGE._value.get()
        self.assertIsNotNone(coverage)
        self.assertGreaterEqual(coverage, 0)
        self.assertLessEqual(coverage, 100)
