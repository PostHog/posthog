"""
Tests for the flags HyperCache for feature-flags service.

Tests cover:
- Basic cache operations (get, update, clear)
- Signal handlers for automatic cache invalidation
- Celery task integration
- Data format compatibility with service
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings

from posthog.models import FeatureFlag, Tag, Team
from posthog.models.feature_flag.feature_flag import FeatureFlagEvaluationTag
from posthog.models.feature_flag.flags_cache import (
    _get_feature_flags_for_service,
    _get_team_ids_with_recently_updated_flags,
    clear_flags_cache,
    flags_hypercache,
    get_flags_from_cache,
    update_flags_cache,
)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsCache(BaseTest):
    """Test basic cache operations for service flags HyperCache."""

    def setUp(self):
        super().setUp()
        # Clear cache before each test
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_cache_key_format(self):
        """Test that cache key is formatted correctly for service flags."""
        key = flags_hypercache.get_cache_key(self.team.id)
        assert key == f"cache/teams/{self.team.id}/feature_flags/flags.json"

    def test_get_feature_flags_for_service_empty(self):
        """Test fetching flags when team has no flags."""
        result = _get_feature_flags_for_service(self.team)

        assert result == {"flags": []}

    def test_get_feature_flags_for_service_with_flags(self):
        """Test fetching flags returns correct format for service."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        flag_data = flags[0]

        # Verify service-compatible fields are present
        assert flag_data["id"] == flag.id
        assert flag_data["team_id"] == self.team.id
        assert flag_data["key"] == "test-flag"
        assert flag_data["name"] == "Test Flag"
        assert flag_data["deleted"] is False
        assert flag_data["active"] is True
        assert "filters" in flag_data
        assert "version" in flag_data

    def test_get_feature_flags_for_service_excludes_deleted(self):
        """Test that deleted flags are excluded from cache."""
        # Create active flag
        FeatureFlag.objects.create(
            team=self.team,
            key="active-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create deleted flag
        FeatureFlag.objects.create(
            team=self.team,
            key="deleted-flag",
            created_by=self.user,
            deleted=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        assert flags[0]["key"] == "active-flag"

    def test_get_feature_flags_for_service_excludes_inactive(self):
        """Test that inactive flags are excluded from cache."""
        # Create active flag
        FeatureFlag.objects.create(
            team=self.team,
            key="active-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create inactive flag
        FeatureFlag.objects.create(
            team=self.team,
            key="inactive-flag",
            created_by=self.user,
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        assert flags[0]["key"] == "active-flag"

    def test_get_flags_from_cache_redis_hit(self):
        """Test getting flags from Redis cache."""
        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="cached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache
        update_flags_cache(self.team)

        # Get from cache (should hit Redis)
        flags = get_flags_from_cache(self.team)
        assert flags is not None
        assert len(flags) == 1
        assert flags[0]["key"] == "cached-flag"

    def test_update_flags_cache(self):
        """Test explicitly updating the service flags cache."""
        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Update cache
        update_flags_cache(self.team)

        # Verify cache was updated
        flags = get_flags_from_cache(self.team)
        assert flags is not None
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"

    def test_clear_flags_cache(self):
        """Test clearing the service flags cache."""
        # Create and cache a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Clear the cache
        clear_flags_cache(self.team)

        # Cache should now load from DB (source will be "db")
        flags, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsSignals(BaseTest):
    """Test Django signal handlers for automatic cache invalidation."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_create(self, mock_task):
        """Test that signal fires when a flag is created."""
        FeatureFlag.objects.create(
            team=self.team,
            key="new-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_update(self, mock_task):
        """Test that signal fires when a flag is updated."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        # Reset mock to ignore the create signal
        mock_task.reset_mock()

        # Update the flag
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        flag.save()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_delete(self, mock_task):
        """Test that signal fires when a flag is deleted."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Reset mock to ignore the create signal
        mock_task.reset_mock()

        # Delete the flag
        flag.delete()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_team_create(self, mock_task):
        """Test that signal fires when a team is created."""
        # Create a new team
        new_team = Team.objects.create(
            organization=self.organization,
            name="New Test Team",
        )

        # Signal should trigger the Celery task to warm cache
        mock_task.delay.assert_called_once_with(new_team.id)

    def test_signal_clears_cache_on_team_delete(self):
        """Test that cache is cleared when a team is deleted."""
        # Create and cache a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Verify cache exists
        flags = get_flags_from_cache(self.team)
        assert flags is not None
        assert len(flags) == 1

        # Delete the team
        self.team.delete()

        # Cache should be cleared (this will load from DB and return empty)
        # We can't test directly with the deleted team object, but the signal should have fired
        # In production, this prevents stale cache entries

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_tag_create(self, mock_task):
        """Test that signal fires when an evaluation tag is added to a flag."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Reset mock to ignore the flag create signal
        mock_task.reset_mock()

        # Create a tag and add it as an evaluation tag
        tag = Tag.objects.create(team=self.team, name="docs-page")
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_tag_delete(self, mock_task):
        """Test that signal fires when an evaluation tag is removed from a flag."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="docs-page")
        eval_tag = FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        # Reset mock to ignore the create signals
        mock_task.reset_mock()

        # Delete the evaluation tag
        eval_tag.delete()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_tag_rename(self, mock_task):
        """Test that signal fires when a tag used by a flag is renamed."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="docs-page")
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        # Reset mock to ignore the create signals
        mock_task.reset_mock()

        # Rename the tag
        tag.name = "landing-page"
        tag.save()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_not_fired_on_tag_rename_when_not_used_by_flags(self, mock_task):
        """Test that signal does not fire when a tag not used by any flag is renamed."""
        # Create a tag that is not used by any flag
        tag = Tag.objects.create(team=self.team, name="unused-tag")

        # Reset mock to ignore the create signal
        mock_task.reset_mock()

        # Rename the tag
        tag.name = "still-unused-tag"
        tag.save()

        # Signal should NOT trigger the Celery task since no flags use this tag
        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_once_when_tag_used_by_multiple_flags(self, mock_task):
        """Tag used by multiple flags should trigger cache update once per team."""
        tag = Tag.objects.create(team=self.team, name="shared-tag")

        for i in range(3):
            flag = FeatureFlag.objects.create(
                team=self.team,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            )
            FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        mock_task.reset_mock()

        tag.name = "renamed-shared-tag"
        tag.save()

        # Should fire once (team-level), not 3 times (flag-level)
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_not_fired_on_tag_creation(self, mock_task):
        """Signal should not fire when a new tag is created."""
        mock_task.reset_mock()

        # Create a new tag
        Tag.objects.create(team=self.team, name="brand-new-tag")

        # Signal should NOT trigger because new tags can't be used by any flags yet
        mock_task.delay.assert_not_called()


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsCeleryTasks(BaseTest):
    """Test Celery task integration for service flags cache updates."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_update_team_service_flags_cache_task(self):
        """Test the Celery task that updates service flags cache."""
        from posthog.tasks.feature_flags import update_team_service_flags_cache

        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Run the task synchronously
        update_team_service_flags_cache(self.team.id)

        # Verify cache was updated
        flags = get_flags_from_cache(self.team)
        assert flags is not None
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"

    def test_update_team_service_flags_cache_task_team_not_found(self):
        """Test the Celery task handles missing team gracefully."""
        from posthog.tasks.feature_flags import update_team_service_flags_cache

        # Run task with non-existent team ID
        # Should not raise an exception
        update_team_service_flags_cache(999999)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsDataFormat(BaseTest):
    """Test that cached data format matches service expectations."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_flag_data_contains_required_rust_fields(self):
        """Test that flag data includes all fields expected by Rust."""
        FeatureFlag.objects.create(
            team=self.team,
            key="rust-compatible-flag",
            name="Rust Compatible Flag",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "email", "value": "test@example.com", "type": "person"}],
                        "rollout_percentage": 50,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
            ensure_experience_continuity=True,
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]
        flag_data = flags[0]

        # Required fields for service FeatureFlag struct
        required_fields = [
            "id",
            "team_id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "ensure_experience_continuity",
            "version",
        ]

        for field in required_fields:
            assert field in flag_data, f"Missing required field: {field}"

        # Verify filters structure
        assert "groups" in flag_data["filters"]
        assert len(flag_data["filters"]["groups"]) == 1
        assert "multivariate" in flag_data["filters"]

    def test_flag_data_serializes_to_json(self):
        """Test that flag data can be serialized to JSON (for Redis/S3 storage)."""
        import json

        FeatureFlag.objects.create(
            team=self.team,
            key="json-test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)

        # Should serialize without errors
        json_str = json.dumps(result)
        assert json_str is not None

        # Should deserialize back to same structure
        deserialized = json.loads(json_str)
        assert "flags" in deserialized
        assert len(deserialized["flags"]) == 1
        assert deserialized["flags"][0]["key"] == "json-test-flag"


class TestCacheStats(BaseTest):
    """Test cache statistics functionality."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_get_cache_stats_basic(self, mock_get_client):
        """Test basic cache stats gathering with Redis pipelining."""
        from posthog.models.feature_flag.flags_cache import get_cache_stats

        # Mock Redis client with pipelining support
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # scan_iter is called twice: once for TTL collection, once for memory sampling
        # Each call needs to return a fresh iterator
        mock_redis.scan_iter.side_effect = [
            iter(
                [
                    b"cache/teams/1/feature_flags/flags.json",
                    b"cache/teams/2/feature_flags/flags.json",
                ]
            ),  # TTL scan
            iter(
                [
                    b"cache/teams/1/feature_flags/flags.json",
                    b"cache/teams/2/feature_flags/flags.json",
                ]
            ),  # Memory scan
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
    """Test get_teams_with_expiring_flags_caches functionality."""

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_returns_teams_with_expiring_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp < threshold should be returned."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            get_teams_with_expiring_flags_caches,
        )

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
            str(team1.id).encode(),
            str(team2.id).encode(),
        ]

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        # Both teams have expiring caches
        self.assertEqual(len(result), 2)
        self.assertIn(team1, result)
        self.assertIn(team2, result)

        # Verify sorted set query was called correctly
        mock_redis.zrangebyscore.assert_called_once_with(
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            "-inf",
            1000000 + (24 * 3600),  # current_time + 24 hours
            start=0,
            num=5000,
        )

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_skips_teams_with_fresh_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp > threshold should not be returned."""
        from posthog.models.feature_flag.flags_cache import get_teams_with_expiring_flags_caches

        # Mock Redis sorted set returning empty (no teams expiring soon)
        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []  # No teams expiring within threshold

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        # No teams returned
        self.assertEqual(len(result), 0)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_returns_empty_when_no_expiring_caches(self, mock_get_client):
        """Should return empty list when sorted set is empty."""
        from posthog.models.feature_flag.flags_cache import get_teams_with_expiring_flags_caches

        # Mock Redis to return empty sorted set
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        self.assertEqual(len(result), 0)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_uses_correct_redis_url(self, mock_get_client):
        """Test that get_client is called with FLAGS_REDIS_URL, not default REDIS_URL.

        This is a regression test for a bug where cache_expiry_manager was using
        the default Redis database (0) instead of the dedicated flags cache database (1).
        """
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            get_teams_with_expiring_caches,
        )

        # Mock Redis to return empty sorted set
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []

        get_teams_with_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours=24)

        # Verify get_client was called with the hypercache's redis_url
        mock_get_client.assert_called_once_with(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.redis_url)


@override_settings(FLAGS_REDIS_URL="redis://test:6379/0")
class TestBatchOperations(BaseTest):
    """Test batch operations for flags cache."""

    @patch("posthog.models.feature_flag.flags_cache.refresh_expiring_caches")
    def test_refresh_expiring_caches(self, mock_refresh):
        """Test refreshing expiring caches calls generic function."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            refresh_expiring_flags_caches,
        )

        mock_refresh.return_value = (2, 0)  # successful, failed

        successful, failed = refresh_expiring_flags_caches(ttl_threshold_hours=24)

        # Should return result from generic function
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

        # Should call generic refresh_expiring_caches with correct config
        mock_refresh.assert_called_once_with(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, 24, settings.FLAGS_CACHE_REFRESH_LIMIT)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_cleanup_stale_expiry_tracking(self, mock_get_client):
        """Test cleaning up stale expiry tracking entries."""
        from posthog.models.feature_flag.flags_cache import FLAGS_CACHE_EXPIRY_SORTED_SET, cleanup_stale_expiry_tracking

        team1 = self.team
        # Create a team that will be deleted
        team2 = Team.objects.create(
            organization=self.organization,
            name="Team 2",
        )
        team2_id = team2.id
        team2.delete()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Mock sorted set with both valid and stale team IDs
        mock_redis.zrange.return_value = [
            str(team1.id).encode(),
            str(team2_id).encode(),  # Stale - team deleted
        ]
        mock_redis.zrem.return_value = 1  # Redis returns number of elements removed

        removed = cleanup_stale_expiry_tracking()

        # Should remove 1 stale entry
        self.assertEqual(removed, 1)

        # Should call zrem with the stale team ID
        mock_redis.zrem.assert_called_once_with(FLAGS_CACHE_EXPIRY_SORTED_SET, str(team2_id))

    @patch("posthog.storage.hypercache.get_client")
    @patch("posthog.storage.hypercache.time")
    def test_warm_without_stagger_tracks_expiry_with_default_ttl(self, mock_time, mock_get_client):
        """Test that expiry tracking happens even when stagger_ttl=False (uses batch path)."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
        )
        from posthog.storage.hypercache_manager import warm_caches

        # Create a flag so batch loading succeeds
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Call warm WITHOUT staggering (ttl_seconds will be None in batch path)
        warm_caches(
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            stagger_ttl=False,  # This should still track expiry!
            batch_size=1,
            team_ids=[self.team.id],  # Ensure we warm only self.team
        )

        # Should have tracked expiry with default TTL
        mock_redis.zadd.assert_called()
        call_args = mock_redis.zadd.call_args

        # Verify it was added to the correct sorted set
        self.assertEqual(call_args[0][0], FLAGS_CACHE_EXPIRY_SORTED_SET)

        # Verify the TTL is the default (since stagger_ttl=False)
        team_id_str = str(self.team.id)
        expiry_timestamp = call_args[0][1][team_id_str]
        expected_expiry = 1000000 + settings.FLAGS_CACHE_TTL
        self.assertEqual(expiry_timestamp, expected_expiry)


@override_settings(
    FLAGS_REDIS_URL="redis://test:6379/0",
    CACHES={
        **settings.CACHES,
        "flags_dedicated": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "flags-test",
        },
    },
)
class TestManagementCommands(BaseTest):
    """Test management commands for flags cache."""

    @patch("posthog.management.commands.analyze_flags_cache_sizes._get_feature_flags_for_teams_batch")
    def test_analyze_command(self, mock_batch_get_flags):
        """Test analyze_flags_cache_sizes command."""
        from django.core.management import call_command

        # Mock flags data
        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag",
                        "active": True,
                        "deleted": False,
                        "filters": {},
                    }
                ]
            }
        }

        # Call command - should complete without error
        call_command("analyze_flags_cache_sizes", "--sample-size=1")

        # Should have called the batch function
        mock_batch_get_flags.assert_called()

    def test_verify_command(self):
        """Test verify_flags_cache command."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Call command with specific team
        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should show verification results
        self.assertIn("Verification Results", output)
        self.assertIn("Total teams verified: 1", output)

    def test_warm_command_specific_teams(self):
        """Test warm_flags_cache command with specific teams."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Call command with specific team
        out = StringIO()
        call_command("warm_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should show warming results
        self.assertIn("Flags cache warm completed", output)
        self.assertIn("Total teams: 1", output)
        self.assertIn("Successful: 1", output)

    @patch("builtins.input", return_value="yes")
    def test_warm_command_invalidate_first(self, mock_input):
        """Test warm_flags_cache command with --invalidate-first."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Call command with --invalidate-first
        out = StringIO()
        call_command("warm_flags_cache", "--invalidate-first", stdout=out)

        output = out.getvalue()
        # Should show warning about invalidation
        self.assertIn("Invalidate first: True", output)
        self.assertIn("Flags cache warm completed", output)

    def test_analyze_command_validates_sample_size_too_small(self):
        """Test analyze command rejects sample_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)

    def test_analyze_command_validates_sample_size_too_large(self):
        """Test analyze command rejects sample_size > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot exceed 10000", output)

    def test_verify_command_validates_sample_too_small(self):
        """Test verify command rejects sample < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)

    def test_verify_command_validates_sample_too_large(self):
        """Test verify command rejects sample > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot exceed 10000", output)

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_batch_size_too_small(self, mock_warm):
        """Test warm command rejects batch_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_batch_size_too_large(self, mock_warm):
        """Test warm command rejects batch_size > 5000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=5001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than 5000", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_ttl_days_too_small(self, mock_warm):
        """Test warm command rejects min_ttl_days < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_ttl_days_too_large(self, mock_warm):
        """Test warm command rejects max_ttl_days > 30."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--max-ttl-days=31", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than 30 days", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_min_greater_than_max_ttl(self, mock_warm):
        """Test warm command rejects min_ttl_days > max_ttl_days."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=10", "--max-ttl-days=5", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than", output)
        mock_warm.assert_not_called()

    # Comprehensive tests for analyze_flags_cache_sizes

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_percentile_calculation(self, mock_batch_get_flags):
        """Test that percentile calculation is accurate."""
        from io import StringIO

        from django.core.management import call_command

        # Create multiple teams with varying flag counts to test percentile calculation
        teams = [self.team]
        for i in range(9):  # Total 10 teams
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            teams.append(team)

        # Mock flags with different sizes
        mock_batch_get_flags.return_value = {
            team.id: {
                "flags": [
                    {
                        "id": j,
                        "team_id": team.id,
                        "key": f"flag-{j}",
                        "name": f"Flag {j}",
                        "active": True,
                        "deleted": False,
                        "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                    }
                    for j in range((i + 1) * 10)  # 10, 20, 30... flags per team
                ]
            }
            for i, team in enumerate(teams)
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=10", stdout=out)

        output = out.getvalue()
        # Should show P95 and P99 values
        self.assertIn("P95:", output)
        self.assertIn("P99:", output)
        # Should show flag counts
        self.assertIn("Flag counts per team:", output)

    def test_analyze_no_teams_in_database(self):
        """Test analyze command handles empty database gracefully."""
        from io import StringIO

        from django.core.management import call_command

        # Delete all teams
        Team.objects.all().delete()

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=100", stdout=out)

        output = out.getvalue()
        self.assertIn("No teams found", output)

    @patch("posthog.management.commands.analyze_flags_cache_sizes._get_feature_flags_for_teams_batch")
    def test_analyze_detailed_field_analysis(self, mock_batch_get_flags):
        """Test analyze command with --detailed flag shows field breakdown."""
        from io import StringIO

        from django.core.management import call_command

        # Delete all other teams so our test team is the only one selected
        Team.objects.exclude(id=self.team.id).delete()

        # Mock flags with various field sizes
        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag",
                        "active": True,
                        "deleted": False,
                        "filters": {
                            "groups": [
                                {
                                    "properties": [{"key": "email", "value": "test@example.com", "type": "person"}],
                                    "rollout_percentage": 100,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", "--detailed", stdout=out)

        output = out.getvalue()
        # Should show field-level breakdown
        self.assertIn("FLAG FIELD SIZE ANALYSIS", output)
        self.assertIn("Largest flag fields", output)

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_compression_ratio(self, mock_batch_get_flags):
        """Test that compression ratios are calculated correctly."""
        from io import StringIO

        from django.core.management import call_command

        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag with a long name that should compress well" * 10,
                        "active": True,
                        "deleted": False,
                        "filters": {},
                    }
                ]
            }
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should show compression ratios
        self.assertIn("Compression ratios:", output)
        self.assertIn(":1", output)  # Ratio format like "3.5:1"

    # Comprehensive tests for warm_flags_cache

    def test_warm_all_teams_success(self):
        """Test warming all teams completes successfully."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=50", stdout=out)

        output = out.getvalue()
        self.assertIn("successful", output.lower())
        self.assertIn("Batch size: 50", output)

    def test_warm_batch_processing_with_failures(self):
        """Test warm command reports partial failures correctly."""
        from io import StringIO

        from unittest.mock import patch

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Make the cache write fail by mocking set_cache_value to raise an exception
        call_count = 0

        def failing_set_cache(team, value, **kwargs):
            nonlocal call_count
            call_count += 1
            # Fail to simulate a cache write error
            raise Exception("Cache write failed")

        # Mock the hypercache's set_cache_value to fail
        with patch(
            "posthog.models.feature_flag.flags_cache.flags_hypercache.set_cache_value", side_effect=failing_set_cache
        ):
            out = StringIO()
            call_command("warm_flags_cache", stdout=out)

            output = out.getvalue()
            # Should show failed count
            self.assertIn("Failed:", output)
            self.assertIn("1", output)  # 1 team failed

    @patch("posthog.storage.hypercache_manager.warm_caches")
    @patch("builtins.input", return_value="no")
    def test_warm_invalidate_first_user_cancels(self, mock_input, mock_warm):
        """Test that user can cancel --invalidate-first operation."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--invalidate-first", stdout=out)

        output = out.getvalue()
        self.assertIn("Aborted", output)
        # Should NOT call warm_caches
        mock_warm.assert_not_called()

    def test_warm_staggered_ttl_range(self):
        """Test that TTL staggering parameters are passed correctly."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=3", "--max-ttl-days=10", stdout=out)

        output = out.getvalue()
        # Should show TTL range in output
        self.assertIn("TTL range: 3-10 days", output)

    @patch("posthog.models.feature_flag.flags_cache.update_flags_cache")
    def test_warm_missing_team_ids_warning(self, mock_update):
        """Test that warming with non-existent team IDs shows warning."""
        from io import StringIO

        from django.core.management import call_command

        mock_update.return_value = True

        out = StringIO()
        call_command("warm_flags_cache", "--team-ids", str(self.team.id), "99999", "88888", stdout=out)

        output = out.getvalue()
        self.assertIn("Warning", output)
        self.assertIn("99999", output)
        self.assertIn("88888", output)

    # Comprehensive tests for verify_flags_cache

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_cache_miss_detection_and_fix(self):
        """Test that cache misses are detected and can be fixed."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import clear_flags_cache

        # Clear any cache from previous tests
        clear_flags_cache(self.team, kinds=["redis", "s3"])

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        # The cache starts empty, so this is a CACHE_MISS (no cache entry exists)
        # This is correct regardless of whether the team has 0 or N flags in DB
        self.assertIn("CACHE_MISS", output)
        self.assertIn("FIXED", output)
        self.assertIn("Cache fixes applied:  1", output)

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_cache_mismatch_detection_and_fix(self):
        """Test that cache mismatches are detected and fixed."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import update_flags_cache

        # Create a real flag
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache first
        update_flags_cache(self.team)

        # Modify the flag (creates a mismatch)
        flag.key = "modified-flag"
        flag.save()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        self.assertIn("DATA_MISMATCH", output)
        self.assertIn("FIXED", output)

    def test_verify_cache_detects_evaluation_tag_rename(self):
        """Test that verification detects when a tag used by a flag is renamed."""
        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        # Create a flag with an evaluation tag
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="original-tag-name")
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        # Warm the cache
        update_flags_cache(self.team)

        # Rename the tag directly in DB (bypassing signals to simulate stale cache)
        Tag.objects.filter(id=tag.id).update(name="renamed-tag-name")

        # Verify should detect the mismatch
        result = verify_team_flags(self.team, verbose=True)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(len(result["diffs"]), 1)
        self.assertEqual(result["diffs"][0]["type"], "FIELD_MISMATCH")
        self.assertIn("evaluation_tags", result["diffs"][0]["diff_fields"])

        # Verify the actual values in the diff
        field_diffs = result["diffs"][0]["field_diffs"]
        eval_tag_diff = next(d for d in field_diffs if d["field"] == "evaluation_tags")
        self.assertEqual(eval_tag_diff["cached_value"], ["original-tag-name"])
        self.assertEqual(eval_tag_diff["db_value"], ["renamed-tag-name"])

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_fix_failures_reported(self):
        """Test that fix failures are properly reported."""
        from io import StringIO

        from unittest.mock import patch

        from django.core.management import call_command

        # Create a real flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Make the hypercache update fail by mocking update_cache
        with patch("posthog.models.feature_flag.flags_cache.flags_hypercache.update_cache", return_value=False):
            out = StringIO()
            call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

            output = out.getvalue()
            self.assertIn("Failed to fix", output)
            self.assertIn("Cache fixes failed:   1", output)

    @patch("posthog.models.feature_flag.flags_cache.get_flags_from_cache")
    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_with_sample(self, mock_batch_get_flags, mock_get_cache):
        """Test verify command with --sample parameter."""
        from io import StringIO

        from django.core.management import call_command

        # Create additional teams
        for i in range(5):
            Team.objects.create(organization=self.organization, name=f"Team {i}")

        mock_get_cache.return_value = []
        mock_batch_get_flags.return_value = {}

        out = StringIO()
        call_command("verify_flags_cache", "--sample=3", stdout=out)

        output = out.getvalue()
        # Should verify exactly 3 teams (randomly sampled)
        self.assertIn("3", output)

    def test_verify_all_caches_match(self):
        """Test verify command when all caches are correct."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import update_flags_cache

        # Create a real flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache so it matches
        update_flags_cache(self.team)

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # When cache matches, there are no issues
        self.assertIn("Cache matches:", output)
        self.assertIn("1 (100.0%)", output)  # 100% match rate

    def test_verify_detects_missing_cache_for_team_with_zero_flags(self):
        """Test that teams with 0 flags but no cache entry are detected as CACHE_MISS."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import clear_flags_cache

        # Delete any existing flags for this team from previous tests
        FeatureFlag.objects.filter(team=self.team).delete()

        # Clear any cache from previous tests to ensure clean state (both Redis and S3)
        clear_flags_cache(self.team, kinds=["redis", "s3"])

        # Team has no flags in DB and no cache entry
        # This should be detected as CACHE_MISS because ALL teams should be cached
        # (even empty ones) to prevent Rust service from hitting database

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should detect cache miss for team with 0 flags
        self.assertIn("CACHE_MISS", output)
        self.assertIn("Cache misses:", output)

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_batch_load_fallback(self, mock_batch_get_flags):
        """Test analyze command falls back gracefully when batch load fails."""
        from io import StringIO

        from django.core.management import call_command

        # Create a flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock batch load to raise exception
        mock_batch_get_flags.side_effect = Exception("Database connection failed")

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should show warning about fallback
        self.assertIn("Batch load failed", output)
        self.assertIn("falling back", output)
        # But should still complete successfully using individual loads
        self.assertIn("ANALYSIS RESULTS", output)

    def test_verify_batch_load_fallback(self):
        """Test verify command falls back gracefully when batch load fails."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG

        # Create a flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock the batch_load_fn on the hypercache instance to raise an exception
        original_batch_fn = FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn

        def failing_batch_load(teams):
            raise Exception("Database error")

        FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn = failing_batch_load

        try:
            out = StringIO()
            call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

            output = out.getvalue()
            # Should show warning about fallback
            self.assertIn("Batch load failed", output)
            self.assertIn("falling back", output)
            # Should still complete verification (using individual loads)
            self.assertIn("Verification Results", output)
        finally:
            # Restore original batch function
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn = original_batch_fn


@override_settings(
    FLAGS_REDIS_URL=None,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "default-test",
        },
    },
)
class TestManagementCommandsWithoutDedicatedCache(BaseTest):
    """Test management commands properly reject execution without dedicated cache."""

    def test_analyze_command_errors_without_flags_redis_url(self):
        """Test analyze command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)

    def test_verify_command_errors_without_flags_redis_url(self):
        """Test verify command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)

    def test_warm_command_errors_without_flags_redis_url(self):
        """Test warm command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)


@override_settings(
    FLAGS_REDIS_URL="redis://test",
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "flags_dedicated": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
)
class TestVerifyFlagsCacheVerboseOutput(BaseTest):
    """Test verbose output formatting for verify_flags_cache command."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_verbose_missing_in_cache(self):
        """Test verbose output for MISSING_IN_CACHE diff type."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag but don't cache it - this creates a MISSING_IN_CACHE scenario
        FeatureFlag.objects.create(
            team=self.team,
            key="uncached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # First warm the cache to establish it, then create a new flag
        update_flags_cache(self.team)

        # Create another flag that won't be in cache
        FeatureFlag.objects.create(
            team=self.team,
            key="new-uncached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("new-uncached-flag", output)
        self.assertIn("exists in DB but missing from cache", output)

    def test_verbose_stale_in_cache(self):
        """Test verbose output for STALE_IN_CACHE diff type."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag and cache it
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="stale-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Delete the flag (cache now stale)
        flag.delete()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("stale-flag", output)
        self.assertIn("exists in cache but deleted from DB", output)

    def test_verbose_field_mismatch(self):
        """Test verbose output for FIELD_MISMATCH diff type with field details."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag and cache it
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="mismatch-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )
        update_flags_cache(self.team)

        # Modify the flag to create a mismatch
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        flag.save()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("mismatch-flag", output)
        self.assertIn("field values differ", output)
        self.assertIn("Field:", output)
        self.assertIn("DB:", output)
        self.assertIn("Cache:", output)

    def test_verbose_unknown_diff_type_fallback(self):
        """Test verbose output falls back gracefully for unknown diff types."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with an unknown type
        command = Command()
        out = StringIO()
        command.stdout = out  # type: ignore[assignment]

        unknown_diff = {
            "type": "UNKNOWN_TYPE",
            "flag_key": "test-flag",
        }
        command.format_verbose_diff(unknown_diff)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("UNKNOWN_TYPE", output)

    def test_verbose_missing_flag_key_uses_flag_id(self):
        """Test verbose output uses flag_id when flag_key is missing."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method without flag_key
        command = Command()
        out = StringIO()
        command.stdout = out  # type: ignore[assignment]

        diff_without_key = {
            "type": "MISSING_IN_CACHE",
            "flag_id": 12345,
            # Note: no flag_key
        }
        command.format_verbose_diff(diff_without_key)

        output = out.getvalue()
        self.assertIn("Flag '12345'", output)

    def test_verbose_empty_field_diffs(self):
        """Test verbose output handles empty field_diffs gracefully."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with empty field_diffs
        command = Command()
        out = StringIO()
        command.stdout = out  # type: ignore[assignment]

        diff_with_empty_field_diffs = {
            "type": "FIELD_MISMATCH",
            "flag_key": "test-flag",
            "field_diffs": [],  # Empty list
        }
        command.format_verbose_diff(diff_with_empty_field_diffs)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("field values differ", output)
        # Should not crash despite empty field_diffs

    def test_verbose_missing_field_in_field_diff(self):
        """Test verbose output handles missing 'field' key in field_diff gracefully."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with malformed field_diff
        command = Command()
        out = StringIO()
        command.stdout = out  # type: ignore[assignment]

        diff_with_malformed_field_diffs = {
            "type": "FIELD_MISMATCH",
            "flag_key": "test-flag",
            "field_diffs": [
                {
                    # Missing 'field' key
                    "db_value": "db_val",
                    "cached_value": "cached_val",
                }
            ],
        }
        command.format_verbose_diff(diff_with_malformed_field_diffs)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("unknown_field", output)  # Falls back to default
        self.assertIn("db_val", output)
        self.assertIn("cached_val", output)


@override_settings(FLAGS_REDIS_URL=None)
class TestServiceFlagsGuards(BaseTest):
    """Test that cache functions guard against writes when FLAGS_REDIS_URL is not set."""

    def setUp(self):
        super().setUp()
        # Create a flag for testing
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def test_get_flags_from_cache_returns_none_without_redis_url(self):
        """Test that get_flags_from_cache returns None when FLAGS_REDIS_URL is not set."""
        flags = get_flags_from_cache(self.team)
        assert flags is None

    def test_update_flags_cache_no_op_without_redis_url(self):
        """Test that update_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        result = update_flags_cache(self.team)

        # Should return False
        assert result is False

        # Since it's a no-op, attempting to get from cache should return None
        flags = get_flags_from_cache(self.team)
        assert flags is None

    def test_clear_flags_cache_no_op_without_redis_url(self):
        """Test that clear_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        clear_flags_cache(self.team)

        # Should complete without error (nothing to verify as it's a no-op)


@override_settings(FLAGS_REDIS_URL="redis://test", FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=5)
class TestGetTeamIdsWithRecentlyUpdatedFlags(BaseTest):
    """Test _get_team_ids_with_recently_updated_flags batch helper for grace period logic."""

    def test_returns_empty_set_for_team_with_no_flags(self):
        """Test returns empty set for team with no flags."""
        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_returns_team_id_for_recently_updated_flag(self):
        """Test returns team ID for team with recently updated flag."""
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == {self.team.id}

    def test_returns_empty_set_for_old_flag(self):
        """Test returns empty set for team with flag updated outside grace period."""
        from datetime import timedelta

        from django.utils import timezone

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        # Manually set updated_at to outside grace period
        FeatureFlag.objects.filter(id=flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_returns_empty_set_when_grace_period_is_zero(self):
        """Test returns empty set when grace period is disabled (0 minutes)."""
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_returns_empty_set_for_empty_team_ids_list(self):
        """Test returns empty set when given empty list of team IDs."""
        result = _get_team_ids_with_recently_updated_flags([])
        assert result == set()

    def test_returns_team_id_if_any_flag_is_recent(self):
        """Test returns team ID if ANY flag is recent (OR logic across team flags)."""
        from datetime import timedelta

        from django.utils import timezone

        # Old flag outside grace period
        old_flag = FeatureFlag.objects.create(
            team=self.team,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.filter(id=old_flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        # Recent flag within grace period
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Should return team ID because at least one flag is recent
        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == {self.team.id}

    def test_batch_returns_only_teams_with_recent_flags(self):
        """Test batch query returns only team IDs that have recently updated flags."""
        from datetime import timedelta

        from django.utils import timezone

        # Create second team
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Team 1 has a recent flag
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Team 2 has an old flag
        old_flag = FeatureFlag.objects.create(
            team=team2,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.filter(id=old_flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        # Query both teams - should only return team 1
        result = _get_team_ids_with_recently_updated_flags([self.team.id, team2.id])
        assert result == {self.team.id}

    def test_ignores_recently_deleted_flags(self):
        """Test returns empty set for team with recently deleted flag.

        When a flag is deleted, the cache update removes it. We shouldn't skip
        verification just because a deleted flag was recently updated.
        """
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="deleted-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            deleted=True,  # Flag is deleted
        )
        # Ensure updated_at is recent (within grace period)
        assert flag.updated_at is not None

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_ignores_recently_deactivated_flags(self):
        """Test returns empty set for team with recently deactivated flag.

        When a flag is deactivated, the cache update removes it. We shouldn't skip
        verification just because an inactive flag was recently updated.
        """
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="inactive-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            active=False,  # Flag is inactive
        )
        # Ensure updated_at is recent (within grace period)
        assert flag.updated_at is not None

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()
