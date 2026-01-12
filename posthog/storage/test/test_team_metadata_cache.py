"""
Tests for team metadata HyperCache functionality.
"""

from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.models.team.team import Team
from posthog.storage.team_metadata_cache import (
    TEAM_METADATA_FIELDS,
    clear_team_metadata_cache,
    get_team_metadata,
    get_teams_with_expiring_caches,
    update_team_metadata_cache,
    verify_team_metadata,
)
from posthog.tasks.team_metadata import update_team_metadata_cache_task


class TestTeamMetadataCache(BaseTest):
    """Test basic team metadata cache functionality."""

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache")
    def test_get_and_update_team_metadata(self, mock_hypercache):
        """Test basic cache read and write operations."""
        # Mock the cache to return metadata
        mock_metadata: dict[str, Any] = {field: None for field in TEAM_METADATA_FIELDS}
        mock_metadata.update({"id": self.team.id, "name": self.team.name})
        mock_hypercache.get_from_cache.return_value = mock_metadata
        mock_hypercache.update_cache.return_value = True

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

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache")
    def test_clear_cache(self, mock_hypercache):
        """Test clearing the cache."""
        mock_metadata = {"id": self.team.id, "name": self.team.name}
        mock_hypercache.get_from_cache.return_value = mock_metadata

        # First populate cache
        update_team_metadata_cache(self.team)

        # Verify it's cached
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

        # Clear and verify it still works (will reload from DB)
        clear_team_metadata_cache(self.team)
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache")
    def test_cache_with_different_key_types(self, mock_hypercache):
        """Test that cache works with team ID and API token."""
        mock_metadata = {"id": self.team.id, "name": self.team.name}
        mock_hypercache.get_from_cache.return_value = mock_metadata
        mock_hypercache.update_cache.return_value = True

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


class TestTeamMetadataCacheTasks(BaseTest):
    """Test Celery tasks for team metadata cache."""

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


class TestTeamMetadataCacheSignals(BaseTest):
    """Test Django signals for cache updates."""

    @patch("posthog.tasks.team_metadata.transaction")
    @patch("posthog.tasks.team_metadata.settings")
    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    def test_team_save_triggers_update(self, mock_task, mock_settings, mock_transaction):
        """Test that saving a team schedules a cache update when FLAGS_REDIS_URL is set."""
        mock_settings.FLAGS_REDIS_URL = "redis://localhost"
        # Make transaction.on_commit execute immediately
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        # Save the existing team to trigger the signal
        self.team.name = "Updated Team"
        self.team.save()

        # Task should be called with the team ID
        mock_task.assert_called_with(self.team.id)

    @patch("posthog.tasks.team_metadata.settings")
    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache")
    def test_team_delete_clears_cache(self, mock_clear, mock_settings):
        """Test that deleting a team clears its cache when FLAGS_REDIS_URL is set."""
        mock_settings.FLAGS_REDIS_URL = "redis://localhost"
        mock_settings.TEST = False

        team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )

        team.delete()

        # Cache should be cleared
        mock_clear.assert_called_once()

    @patch("posthog.tasks.team_metadata.transaction")
    @patch("posthog.tasks.team_metadata.settings")
    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    def test_team_save_noop_without_flags_redis_url(self, mock_task, mock_settings, mock_transaction):
        """Test that signal is no-op when FLAGS_REDIS_URL is not set."""
        mock_settings.FLAGS_REDIS_URL = None
        # Make transaction.on_commit execute immediately
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        # Save the existing team
        self.team.name = "Updated Team"
        self.team.save()

        # Task should NOT be called
        mock_task.assert_not_called()

    @patch("posthog.tasks.team_metadata.settings")
    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache")
    def test_team_delete_noop_without_flags_redis_url(self, mock_clear, mock_settings):
        """Test that signal is no-op when FLAGS_REDIS_URL is not set."""
        mock_settings.FLAGS_REDIS_URL = None

        # Create and delete a new team for this test
        team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )
        team.delete()

        # Cache should NOT be cleared
        mock_clear.assert_not_called()


class TestCacheStats(BaseTest):
    """Test cache statistics functionality."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_get_cache_stats_basic(self, mock_get_client):
        """Test basic cache stats gathering with Redis pipelining."""
        from posthog.storage.team_metadata_cache import get_cache_stats

        # Mock Redis client with pipelining support
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # scan_iter is called twice: once for TTL collection, once for memory sampling
        # Each call needs to return a fresh iterator
        mock_redis.scan_iter.side_effect = [
            iter([b"cache:team_metadata:key1", b"cache:team_metadata:key2"]),  # TTL scan
            iter([b"cache:team_metadata:key1", b"cache:team_metadata:key2"]),  # Memory scan
        ]

        # Mock pipeline for batched operations
        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.side_effect = [
            [3600, 86400],  # TTL results: 1 hour, 1 day
            [1024, 2048],  # Memory usage results
        ]

        # Mock zcard for expiry tracking count
        mock_redis.zcard.return_value = 2

        with patch("posthog.models.team.team.Team.objects.count", return_value=5):
            stats = get_cache_stats()

        self.assertEqual(stats["total_cached"], 2)
        self.assertEqual(stats["total_teams"], 5)
        self.assertEqual(stats["expiry_tracked"], 2)
        self.assertEqual(stats["ttl_distribution"]["expires_1h"], 1)
        self.assertEqual(stats["ttl_distribution"]["expires_24h"], 1)
        self.assertEqual(stats["size_statistics"]["sample_count"], 2)
        self.assertEqual(stats["size_statistics"]["avg_size_bytes"], 1536)  # (1024 + 2048) / 2


class TestGetTeamsWithExpiringCaches(BaseTest):
    """Test get_teams_with_expiring_caches functionality."""

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_returns_teams_with_expiring_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp < threshold should be returned."""
        team1 = self.team
        team2 = Team.objects.create(
            organization=self.organization,
            name="Team 2",
        )

        # Mock current time and Redis sorted set query
        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Return teams expiring within next 24 hours
        mock_redis.zrangebyscore.return_value = [
            team1.api_token.encode(),
            team2.api_token.encode(),
        ]

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        # Both teams have expiring caches
        self.assertEqual(len(result), 2)
        self.assertIn(team1, result)
        self.assertIn(team2, result)

        # Verify sorted set query was called correctly with limit
        mock_redis.zrangebyscore.assert_called_once_with(
            "team_metadata_cache_expiry",
            "-inf",
            1000000 + (24 * 3600),  # current_time + 24 hours
            start=0,
            num=5000,
        )

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_skips_teams_with_fresh_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp > threshold should not be returned."""
        # Mock Redis sorted set returning empty (no teams expiring soon)
        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []  # No teams expiring within threshold

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        # Team has fresh cache, not returned
        self.assertEqual(len(result), 0)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_returns_empty_when_no_expiring_caches(self, mock_get_client):
        """Should return empty list when sorted set is empty."""
        # Mock Redis to return empty sorted set
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []

        result = get_teams_with_expiring_caches(ttl_threshold_hours=24)

        self.assertEqual(len(result), 0)


class TestVerifyTeamMetadata(BaseTest):
    """Test verify_team_metadata functionality."""

    @patch("posthog.storage.team_metadata_cache.get_team_metadata")
    def test_verify_ignores_extra_cached_fields(self, mock_get_metadata):
        """
        Verify that extra fields in cache (not in TEAM_METADATA_FIELDS) are ignored.

        This allows removing fields from TEAM_METADATA_FIELDS without triggering
        unnecessary cache fixes for stale fields that remain in cached data.
        """
        from posthog.storage.team_metadata_cache import _serialize_team_to_metadata

        # Get the actual serialized data for this team (what DB would return)
        db_data = _serialize_team_to_metadata(self.team)

        # Create cached data that matches DB data but has extra fields
        cached_data = db_data.copy()
        cached_data.update(
            {
                # Extra fields that might exist in old cached data but are no longer in TEAM_METADATA_FIELDS
                "removed_field_1": "stale_value",
                "removed_field_2": {"old": "data"},
                "updated_at": "2025-01-01T00:00:00Z",  # Common field that might be removed
                "app_urls": [],  # Another removed field
            }
        )
        mock_get_metadata.return_value = cached_data

        # Verify should report a match since extra fields are ignored
        result = verify_team_metadata(self.team, verbose=True)

        self.assertEqual(result["status"], "match", f"Expected match but got {result}")

    @patch("posthog.storage.team_metadata_cache.get_team_metadata")
    def test_verify_detects_mismatch_in_tracked_fields(self, mock_get_metadata):
        """Verify that mismatches in TEAM_METADATA_FIELDS are still detected."""
        from posthog.storage.team_metadata_cache import _serialize_team_to_metadata

        # Get the actual serialized data for this team
        db_data = _serialize_team_to_metadata(self.team)

        # Create cached data with a mismatch in a tracked field
        cached_data = db_data.copy()
        cached_data["name"] = "Wrong Name"  # Mismatch in a tracked field
        mock_get_metadata.return_value = cached_data

        result = verify_team_metadata(self.team)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["issue"], "DATA_MISMATCH")
        self.assertIn("name", result["diff_fields"])

    @patch("posthog.storage.team_metadata_cache.get_team_metadata")
    def test_verify_returns_miss_when_no_cached_data(self, mock_get_metadata):
        """Verify returns cache miss when no data is cached."""
        mock_get_metadata.return_value = None

        result = verify_team_metadata(self.team)

        self.assertEqual(result["status"], "miss")
        self.assertEqual(result["issue"], "CACHE_MISS")


@override_settings(FLAGS_REDIS_URL="redis://test:6379/0")
class TestWarmCachesExpiryTracking(BaseTest):
    """
    Test that warm_caches uses the correct identifier for expiry tracking.

    This is a regression test for a bug where warm_caches used team IDs for
    expiry tracking, but the team_metadata cache is token-based and expects
    API tokens. This caused a mismatch between cache entries and expiry tracking.
    """

    @patch("posthog.storage.hypercache.get_client")
    @patch("posthog.storage.hypercache.time")
    def test_warm_caches_uses_api_token_for_token_based_cache(self, mock_time, mock_get_client):
        """
        Verify that warm_caches uses API token (not team ID) for token-based caches.

        The team_metadata cache is token-based (token_based=True), so expiry
        tracking should use the API token as the identifier, not the team ID.
        """
        from posthog.storage.hypercache_manager import warm_caches
        from posthog.storage.team_metadata_cache import TEAM_CACHE_EXPIRY_SORTED_SET, TEAM_HYPERCACHE_MANAGEMENT_CONFIG

        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Call warm_caches for this team
        warm_caches(
            TEAM_HYPERCACHE_MANAGEMENT_CONFIG,
            stagger_ttl=False,
            batch_size=1,
            team_ids=[self.team.id],
        )

        # Verify zadd was called with the API TOKEN, not team ID
        mock_redis.zadd.assert_called()
        call_args = mock_redis.zadd.call_args

        # First arg is the sorted set key
        self.assertEqual(call_args[0][0], TEAM_CACHE_EXPIRY_SORTED_SET)

        # Second arg is a dict with identifier -> timestamp
        # The identifier should be the API token, NOT the team ID
        identifier_dict = call_args[0][1]
        self.assertIn(
            self.team.api_token,
            identifier_dict,
            f"Expected API token '{self.team.api_token}' as identifier, "
            f"but got: {list(identifier_dict.keys())}. "
            "This indicates warm_caches is using the wrong identifier type for token-based caches.",
        )
        self.assertNotIn(
            str(self.team.id),
            identifier_dict,
            f"Found team ID '{self.team.id}' as identifier, but token-based caches should use API tokens.",
        )


@override_settings(FLAGS_REDIS_URL="redis://test", TEST=True)
class TestTeamMetadataGracePeriod(BaseTest):
    """Test grace period functionality for team metadata cache verification."""

    def test_recently_updated_team_is_in_skip_set(self):
        """Test that a recently updated team is included in the skip set."""
        from posthog.storage.team_metadata_cache import _get_team_ids_with_recently_updated_teams

        # Team was just created, so updated_at is recent
        result = _get_team_ids_with_recently_updated_teams([self.team.id])
        self.assertIn(self.team.id, result)

    def test_old_team_is_not_in_skip_set(self):
        """Test that a team updated long ago is not in the skip set."""
        from datetime import timedelta

        from django.utils import timezone

        from posthog.storage.team_metadata_cache import _get_team_ids_with_recently_updated_teams

        # Update the team to have an old updated_at
        old_time = timezone.now() - timedelta(hours=1)
        Team.objects.filter(id=self.team.id).update(updated_at=old_time)

        result = _get_team_ids_with_recently_updated_teams([self.team.id])
        self.assertNotIn(self.team.id, result)

    @override_settings(TEAM_METADATA_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_grace_period_disabled_returns_empty(self):
        """Test that setting grace period to 0 disables the feature."""
        from posthog.storage.team_metadata_cache import _get_team_ids_with_recently_updated_teams

        result = _get_team_ids_with_recently_updated_teams([self.team.id])
        self.assertEqual(result, set())

    def test_empty_team_ids_returns_empty(self):
        """Test that empty input returns empty set."""
        from posthog.storage.team_metadata_cache import _get_team_ids_with_recently_updated_teams

        result = _get_team_ids_with_recently_updated_teams([])
        self.assertEqual(result, set())

    def test_config_has_skip_fix_function(self):
        """Test that the config is wired up with the skip fix function."""
        from posthog.storage.team_metadata_cache import TEAM_HYPERCACHE_MANAGEMENT_CONFIG

        self.assertIsNotNone(TEAM_HYPERCACHE_MANAGEMENT_CONFIG.get_team_ids_to_skip_fix_fn)
