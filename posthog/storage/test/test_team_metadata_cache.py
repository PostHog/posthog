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
    get_teams_needing_refresh,
    update_team_metadata_cache,
)
from posthog.tasks.team_metadata import refresh_stale_team_metadata_cache, update_team_metadata_cache_task


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


class TestGetTeamsNeedingRefresh(TransactionTestCase):
    """Test get_teams_needing_refresh query performance."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_query_count_with_few_teams(self, mock_get_client):
        """Test that query count is constant with 3 teams."""
        # Create 3 teams
        teams = [
            Team.objects.create(
                organization=self.organization,
                name=f"Team {i}",
                ingested_event=True,
            )
            for i in range(3)
        ]

        # Mock Redis to return expiring tokens for 2 teams
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            f"cache/team_tokens/{teams[0].api_token}/team_metadata/full_metadata.json".encode(),
            f"cache/team_tokens/{teams[1].api_token}/team_metadata/full_metadata.json".encode(),
        ]
        mock_redis.ttl.return_value = 3600  # 1 hour TTL (expiring soon)

        # Should be exactly 2 queries:
        # 1. Get teams with expiring caches
        # 2. Get additional active teams (if needed)
        with self.assertNumQueries(2):
            result = get_teams_needing_refresh(batch_size=10)

        self.assertGreater(len(result), 0)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_query_count_with_many_teams(self, mock_get_client):
        """Test that query count remains constant with 50 teams."""
        # Create 50 teams
        teams = [
            Team.objects.create(
                organization=self.organization,
                name=f"Team {i}",
                ingested_event=True,
            )
            for i in range(50)
        ]

        # Mock Redis to return expiring tokens for 20 teams
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        expiring_keys = [
            f"cache/team_tokens/{team.api_token}/team_metadata/full_metadata.json".encode() for team in teams[:20]
        ]
        mock_redis.scan_iter.return_value = expiring_keys
        mock_redis.ttl.return_value = 3600  # 1 hour TTL

        # Should still be exactly 2 queries regardless of team count
        with self.assertNumQueries(2):
            result = get_teams_needing_refresh(batch_size=100)

        self.assertGreater(len(result), 0)
        # Should get the 20 teams with expiring caches plus up to 80 more
        self.assertLessEqual(len(result), 100)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_query_count_when_batch_filled_by_expiring(self, mock_get_client):
        """Test query count when batch_size is filled by expiring caches only."""
        # Create 20 teams
        teams = [
            Team.objects.create(
                organization=self.organization,
                name=f"Team {i}",
                ingested_event=True,
            )
            for i in range(20)
        ]

        # Mock Redis to return expiring tokens for all 20 teams
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        expiring_keys = [
            f"cache/team_tokens/{team.api_token}/team_metadata/full_metadata.json".encode() for team in teams
        ]
        mock_redis.scan_iter.return_value = expiring_keys
        mock_redis.ttl.return_value = 3600  # 1 hour TTL

        # When batch_size is filled by expiring caches, should only be 1 query
        # (no need for the second query to find additional active teams)
        with self.assertNumQueries(1):
            result = get_teams_needing_refresh(batch_size=10)

        self.assertEqual(len(result), 10)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_query_count_with_redis_error(self, mock_get_client):
        """Test that query count is still constant even when Redis fails."""
        # Create 10 teams
        for i in range(10):
            Team.objects.create(
                organization=self.organization,
                name=f"Team {i}",
                ingested_event=True,
            )

        # Mock Redis to raise an exception
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.side_effect = Exception("Redis connection failed")

        # Should gracefully handle the error and fall back to DB-only query
        # Should be exactly 1 query (finding active teams)
        with self.assertNumQueries(1):
            result = get_teams_needing_refresh(batch_size=5)

        # Should still return teams (from the fallback query)
        self.assertGreater(len(result), 0)
        self.assertLessEqual(len(result), 5)


class TestTeamMetadataCacheBatchMetrics(BaseTest):
    """Test Prometheus metrics for batch refresh job."""

    def test_batch_refresh_metrics(self):
        """Test that batch refresh updates all expected metrics."""
        update_team_metadata_cache(self.team)

        before_counter = TEAM_METADATA_BATCH_REFRESH_COUNTER.labels(result="success")._value.get()
        before_teams_success = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="success")._value.get()
        before_teams_failed = TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="failed")._value.get()

        refresh_stale_team_metadata_cache()

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

        refresh_stale_team_metadata_cache()

        coverage = TEAM_METADATA_CACHE_COVERAGE_GAUGE._value.get()
        self.assertIsNotNone(coverage)
        self.assertGreaterEqual(coverage, 0)
        self.assertLessEqual(coverage, 100)
