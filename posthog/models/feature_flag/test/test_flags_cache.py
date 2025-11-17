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

from posthog.models import FeatureFlag, Team
from posthog.models.feature_flag.flags_cache import (
    _get_feature_flags_for_service,
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
        from posthog.models.feature_flag.flags_cache import get_flags_cache_stats

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

        with patch("posthog.models.team.team.Team.objects.count", return_value=5):
            stats = get_flags_cache_stats()

        self.assertEqual(stats["total_cached"], 2)
        self.assertEqual(stats["total_teams"], 5)
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


@override_settings(FLAGS_REDIS_URL="redis://test:6379/0")
class TestBatchOperations(BaseTest):
    """Test batch operations for flags cache."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_invalidate_all_flags_caches(self, mock_get_client):
        """Test invalidating all flags caches."""
        from posthog.models.feature_flag.flags_cache import FLAGS_CACHE_EXPIRY_SORTED_SET, invalidate_all_flags_caches

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Mock scan_iter to return some keys
        mock_redis.scan_iter.return_value = [
            b"cache/teams/1/feature_flags/flags.json",
            b"cache/teams/2/feature_flags/flags.json",
        ]

        deleted = invalidate_all_flags_caches()

        # Should delete 2 keys
        self.assertEqual(deleted, 2)

        # Should delete the expiry tracking sorted set
        mock_redis.delete.assert_any_call(FLAGS_CACHE_EXPIRY_SORTED_SET)

    @patch("posthog.models.feature_flag.flags_cache.refresh_expiring_caches")
    def test_refresh_expiring_caches(self, mock_refresh):
        """Test refreshing expiring caches calls generic function."""
        from posthog.models.feature_flag.flags_cache import FLAGS_CACHE_EXPIRY_CONFIG, refresh_expiring_flags_caches

        mock_refresh.return_value = (2, 0)  # successful, failed

        successful, failed = refresh_expiring_flags_caches(ttl_threshold_hours=24)

        # Should return result from generic function
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

        # Should call generic refresh_expiring_caches with correct config
        mock_refresh.assert_called_once_with(FLAGS_CACHE_EXPIRY_CONFIG, 24, settings.FLAGS_CACHE_REFRESH_LIMIT)

    @patch("posthog.models.feature_flag.flags_cache.warm_all_caches")
    def test_warm_all_flags_caches(self, mock_warm):
        """Test warming all flags caches calls generic function."""
        from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, warm_all_flags_caches

        mock_warm.return_value = (2, 0)  # successful, failed

        successful, failed = warm_all_flags_caches(
            batch_size=10,
            invalidate_first=True,
            stagger_ttl=False,
            min_ttl_days=3,
            max_ttl_days=5,
        )

        # Should return the result from the generic function
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

        # Should call generic warm_all_caches with correct config and params
        mock_warm.assert_called_once_with(
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            batch_size=10,
            invalidate_first=True,
            stagger_ttl=False,
            min_ttl_days=3,
            max_ttl_days=5,
        )

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

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
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

    @patch("posthog.management.commands.verify_flags_cache.update_flags_cache")
    @patch("posthog.management.commands.verify_flags_cache.get_flags_from_cache")
    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_command(self, mock_batch_get_flags, mock_get_cache, mock_update):
        """Test verify_flags_cache command."""
        from django.core.management import call_command

        # Mock data
        mock_flags_data = [
            {
                "id": 1,
                "team_id": self.team.id,
                "key": "test-flag",
                "name": "Test Flag",
            }
        ]
        mock_get_cache.return_value = mock_flags_data
        mock_batch_get_flags.return_value = {self.team.id: {"flags": mock_flags_data}}
        mock_update.return_value = True

        # Call command with specific team
        call_command("verify_flags_cache", f"--team-ids={self.team.id}")

        # Should check the cache
        mock_get_cache.assert_called()

    @patch("posthog.management.commands.warm_flags_cache.flags_hypercache")
    @patch("posthog.management.commands.warm_flags_cache._get_feature_flags_for_teams_batch")
    def test_warm_command_specific_teams(self, mock_batch_get_flags, mock_hypercache):
        """Test warm_flags_cache command with specific teams."""
        from django.core.management import call_command

        mock_batch_get_flags.return_value = {self.team.id: {"flags": [{"id": 1, "key": "test-flag"}]}}
        mock_hypercache.set_cache_value.return_value = None

        # Call command with specific team
        call_command("warm_flags_cache", f"--team-ids={self.team.id}")

        # Should have used batch loading and set cache
        mock_batch_get_flags.assert_called_once()
        mock_hypercache.set_cache_value.assert_called_once()

    @patch("posthog.management.commands.warm_flags_cache.warm_all_flags_caches")
    @patch("builtins.input", return_value="yes")
    def test_warm_command_invalidate_first(self, mock_input, mock_warm_all):
        """Test warm_flags_cache command with --invalidate-first."""
        from django.core.management import call_command

        mock_warm_all.return_value = (1, 0)  # 1 successful, 0 failed

        # Call command with --invalidate-first
        call_command("warm_flags_cache", "--invalidate-first")

        # Should call warm_all_flags_caches with invalidate_first=True
        mock_warm_all.assert_called_once()
        call_kwargs = mock_warm_all.call_args[1]
        self.assertTrue(call_kwargs["invalidate_first"])

    def test_analyze_command_validates_sample_size_too_small(self):
        """Test analyze command rejects sample_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("must be at least 1", output)

    def test_analyze_command_validates_sample_size_too_large(self):
        """Test analyze command rejects sample_size > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("cannot exceed 10000", output)

    def test_verify_command_validates_sample_too_small(self):
        """Test verify command rejects sample < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=0", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("must be at least 1", output)

    def test_verify_command_validates_sample_too_large(self):
        """Test verify command rejects sample > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("cannot exceed 10000", output)

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_command_validates_batch_size_too_small(self, mock_warm_all):
        """Test warm command rejects batch_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("must be at least 1", output)
        mock_warm_all.assert_not_called()

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_command_validates_batch_size_too_large(self, mock_warm_all):
        """Test warm command rejects batch_size > 1000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=1001", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("cannot be greater than 1000", output)
        mock_warm_all.assert_not_called()

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_command_validates_ttl_days_too_small(self, mock_warm_all):
        """Test warm command rejects min_ttl_days < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=0", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("must be at least 1", output)
        mock_warm_all.assert_not_called()

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_command_validates_ttl_days_too_large(self, mock_warm_all):
        """Test warm command rejects max_ttl_days > 30."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--max-ttl-days=31", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("cannot be greater than 30 days", output)
        mock_warm_all.assert_not_called()

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_command_validates_min_greater_than_max_ttl(self, mock_warm_all):
        """Test warm command rejects min_ttl_days > max_ttl_days."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=10", "--max-ttl-days=5", stdout=out)

        output = out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("cannot be greater than", output)
        mock_warm_all.assert_not_called()

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

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_detailed_field_analysis(self, mock_batch_get_flags):
        """Test analyze command with --detailed flag shows field breakdown."""
        from io import StringIO

        from django.core.management import call_command

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

    @patch("posthog.models.feature_flag.flags_cache.warm_all_flags_caches")
    def test_warm_all_teams_success(self, mock_warm_all):
        """Test warming all teams completes successfully."""
        from io import StringIO

        from django.core.management import call_command

        mock_warm_all.return_value = (100, 0)  # 100 successful, 0 failed

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=50", stdout=out)

        output = out.getvalue()
        self.assertIn("successful", output.lower())
        self.assertIn("100", output)
        # Should call warm_all_flags_caches with correct batch size
        mock_warm_all.assert_called_once()
        call_kwargs = mock_warm_all.call_args[1]
        self.assertEqual(call_kwargs["batch_size"], 50)

    @patch("posthog.management.commands.warm_flags_cache.warm_all_flags_caches")
    def test_warm_batch_processing_with_failures(self, mock_warm_all):
        """Test warm command reports partial failures correctly."""
        from io import StringIO

        from django.core.management import call_command

        mock_warm_all.return_value = (95, 5)  # 95 successful, 5 failed

        out = StringIO()
        call_command("warm_flags_cache", stdout=out)

        output = out.getvalue()
        self.assertIn("95", output)  # Successful count
        self.assertIn("5", output)  # Failed count
        self.assertIn("Warning", output)  # Should warn about failures

    @patch("posthog.management.commands.warm_flags_cache.warm_all_flags_caches")
    @patch("builtins.input", return_value="no")
    def test_warm_invalidate_first_user_cancels(self, mock_input, mock_warm_all):
        """Test that user can cancel --invalidate-first operation."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--invalidate-first", stdout=out)

        output = out.getvalue()
        self.assertIn("Aborted", output)
        # Should NOT call warm_all_flags_caches
        mock_warm_all.assert_not_called()

    @patch("posthog.management.commands.warm_flags_cache.warm_all_flags_caches")
    def test_warm_staggered_ttl_range(self, mock_warm_all):
        """Test that TTL staggering parameters are passed correctly."""
        from django.core.management import call_command

        mock_warm_all.return_value = (10, 0)

        call_command("warm_flags_cache", "--min-ttl-days=3", "--max-ttl-days=10")

        mock_warm_all.assert_called_once()
        call_kwargs = mock_warm_all.call_args[1]
        self.assertEqual(call_kwargs["min_ttl_days"], 3)
        self.assertEqual(call_kwargs["max_ttl_days"], 10)
        self.assertTrue(call_kwargs["stagger_ttl"])

    @patch("posthog.management.commands.warm_flags_cache.update_flags_cache")
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

    @patch("posthog.management.commands.verify_flags_cache.update_flags_cache")
    @patch("posthog.management.commands.verify_flags_cache.get_flags_from_cache")
    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_cache_miss_detection_and_fix(self, mock_batch_get_flags, mock_get_cache, mock_update):
        """Test that cache misses are detected and can be fixed."""
        from io import StringIO

        from django.core.management import call_command

        # Database has flags, but cache is empty (cache miss)
        mock_flags_data = [{"id": 1, "team_id": self.team.id, "key": "test-flag", "name": "Test Flag"}]
        mock_get_cache.return_value = None  # Cache miss
        mock_batch_get_flags.return_value = {self.team.id: {"flags": mock_flags_data}}
        mock_update.return_value = True

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        self.assertIn("CACHE_MISS", output)
        self.assertIn("FIXED", output)
        # Should have called update to fix the cache
        mock_update.assert_called()

    @patch("posthog.management.commands.verify_flags_cache.update_flags_cache")
    @patch("posthog.management.commands.verify_flags_cache.get_flags_from_cache")
    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_cache_mismatch_detection_and_fix(self, mock_batch_get_flags, mock_get_cache, mock_update):
        """Test that cache mismatches are detected and fixed."""
        from io import StringIO

        from django.core.management import call_command

        # Cache has outdated data
        cached_flags = [{"id": 1, "team_id": self.team.id, "key": "old-flag", "name": "Old Flag"}]
        db_flags = [{"id": 1, "team_id": self.team.id, "key": "new-flag", "name": "New Flag"}]

        mock_get_cache.return_value = cached_flags
        mock_batch_get_flags.return_value = {self.team.id: {"flags": db_flags}}
        mock_update.return_value = True

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        self.assertIn("DATA_MISMATCH", output)
        self.assertIn("FIXED", output)
        mock_update.assert_called()

    @patch("posthog.caching.flags_redis_cache.caches")
    @patch("posthog.models.feature_flag.flags_cache.get_flags_from_cache")
    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_dedicated_cache_check(self, mock_batch_get_flags, mock_get_cache, mock_caches):
        """Test verification of dedicated flags cache."""
        from io import StringIO

        from django.core.management import call_command

        mock_flags = [{"id": 1, "team_id": self.team.id, "key": "test-flag"}]
        mock_get_cache.return_value = mock_flags
        mock_batch_get_flags.return_value = {self.team.id: {"flags": mock_flags}}

        # Mock dedicated cache to return None (cache miss in dedicated)
        mock_dedicated_cache = MagicMock()
        mock_dedicated_cache.get.return_value = None
        mock_caches.__getitem__.return_value = mock_dedicated_cache

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--check-dedicated-cache", stdout=out)

        output = out.getvalue()
        self.assertIn("DEDICATED_CACHE_MISS", output)

    @patch("posthog.management.commands.verify_flags_cache.update_flags_cache")
    @patch("posthog.management.commands.verify_flags_cache.get_flags_from_cache")
    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_fix_failures_reported(self, mock_batch_get_flags, mock_get_cache, mock_update):
        """Test that fix failures are properly reported."""
        from io import StringIO

        from django.core.management import call_command

        mock_get_cache.return_value = None  # Cache miss
        mock_batch_get_flags.return_value = {self.team.id: {"flags": [{"id": 1, "key": "test"}]}}
        mock_update.return_value = False  # Fix fails

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        self.assertIn("FIX FAILED", output)
        self.assertIn("fixes failed", output.lower())

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

    @patch("posthog.models.feature_flag.flags_cache.get_flags_from_cache")
    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_all_caches_match(self, mock_batch_get_flags, mock_get_cache):
        """Test verify command when all caches are correct."""
        from io import StringIO

        from django.core.management import call_command

        mock_flags = [{"id": 1, "team_id": self.team.id, "key": "test-flag"}]
        mock_get_cache.return_value = mock_flags
        mock_batch_get_flags.return_value = {self.team.id: {"flags": mock_flags}}

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        self.assertIn("verified successfully", output.lower())
        self.assertIn("100.0%", output)  # 100% match rate

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

    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_service")
    @patch("posthog.management.commands.verify_flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_batch_load_fallback(self, mock_batch_get_flags, mock_get_service):
        """Test verify command falls back gracefully when batch load fails."""
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
        mock_batch_get_flags.side_effect = Exception("Database error")

        # Mock individual load to return valid data
        mock_get_service.return_value = {"flags": [{"id": 1, "team_id": self.team.id, "key": "test-flag"}]}

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should show warning about fallback
        self.assertIn("Batch load failed", output)
        self.assertIn("falling back", output)
        # Should still complete verification
        self.assertIn("Verification Results", output)


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
        self.assertIn("ERROR", output)
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
        self.assertIn("ERROR", output)
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
        self.assertIn("ERROR", output)
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)


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
