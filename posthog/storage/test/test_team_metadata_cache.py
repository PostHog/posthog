"""
Tests for team metadata HyperCache functionality.
"""

from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCacheStoreMissing
from posthog.storage.team_metadata_cache import (
    TEAM_METADATA_FIELDS,
    _load_team_metadata,
    clear_team_metadata_cache,
    get_team_metadata,
    update_team_metadata_cache,
)
from posthog.tasks.team_metadata import (
    sync_all_team_metadata_cache,
    update_team_metadata_cache_batch,
    update_team_metadata_cache_task,
)


class TestTeamMetadataCache(BaseTest):
    """Test team metadata cache functionality."""

    def setUp(self):
        super().setUp()
        # Clear any existing cache entries
        clear_team_metadata_cache(self.team, kinds=["redis", "s3"])

    def test_load_team_metadata_with_team_object(self):
        """Test loading metadata with a Team object."""
        metadata = _load_team_metadata(self.team)

        assert isinstance(metadata, dict)
        self.assertEqual(metadata["id"], self.team.id)
        self.assertEqual(metadata["api_token"], self.team.api_token)
        self.assertEqual(metadata["name"], self.team.name)
        self.assertEqual(metadata["organization_name"], self.organization.name)

        # Check all required fields are present
        for field in TEAM_METADATA_FIELDS:
            self.assertIn(field, metadata)

        # Check computed fields
        self.assertIn("last_updated", metadata)
        self.assertIn("project_name", metadata)

    def test_load_team_metadata_with_api_token(self):
        """Test loading metadata with an API token string."""
        metadata = _load_team_metadata(self.team.api_token)

        assert isinstance(metadata, dict)
        self.assertEqual(metadata["id"], self.team.id)
        self.assertEqual(metadata["api_token"], self.team.api_token)

    def test_load_team_metadata_with_team_id(self):
        """Test loading metadata with a team ID."""
        metadata = _load_team_metadata(self.team.id)

        assert isinstance(metadata, dict)
        self.assertEqual(metadata["id"], self.team.id)
        self.assertEqual(metadata["api_token"], self.team.api_token)

    def test_load_team_metadata_nonexistent_team(self):
        """Test loading metadata for a non-existent team."""
        result = _load_team_metadata("nonexistent_token")

        self.assertIsInstance(result, HyperCacheStoreMissing)

    def test_get_team_metadata_cold_cache(self):
        """Test getting metadata when cache is cold (from DB)."""
        # Ensure cache is empty
        clear_team_metadata_cache(self.team, kinds=["redis", "s3"])

        with self.assertNumQueries(2):  # One for team_from_key, one for select_related
            metadata = get_team_metadata(self.team)

        assert metadata is not None
        self.assertEqual(metadata["id"], self.team.id)
        self.assertEqual(metadata["api_token"], self.team.api_token)

        # Second call should hit Redis cache
        with self.assertNumQueries(0):
            metadata2 = get_team_metadata(self.team)

        self.assertEqual(metadata, metadata2)

    def test_get_team_metadata_warm_cache(self):
        """Test getting metadata when cache is warm (from Redis)."""
        # Warm the cache
        update_team_metadata_cache(self.team)

        # Get from cache - should not hit DB
        with self.assertNumQueries(0):
            metadata = get_team_metadata(self.team)

        assert metadata is not None
        self.assertEqual(metadata["id"], self.team.id)

    def test_update_team_metadata_cache(self):
        """Test updating the metadata cache."""
        success = update_team_metadata_cache(self.team)

        self.assertTrue(success)

        # Verify cache was updated
        metadata = get_team_metadata(self.team)
        assert metadata is not None
        self.assertEqual(metadata["id"], self.team.id)

    def test_clear_team_metadata_cache(self):
        """Test clearing the metadata cache."""
        # First warm the cache
        update_team_metadata_cache(self.team)

        # Verify it's cached
        with self.assertNumQueries(0):
            metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

        # Clear the cache
        clear_team_metadata_cache(self.team, kinds=["redis"])

        # Now it should hit the DB (or S3)
        metadata = get_team_metadata(self.team)
        self.assertIsNotNone(metadata)

    def test_cache_includes_all_fields(self):
        """Test that cached metadata includes all specified fields."""
        metadata = get_team_metadata(self.team)

        assert metadata is not None
        for field in TEAM_METADATA_FIELDS:
            self.assertIn(field, metadata, f"Field {field} missing from cached metadata")

    @freeze_time("2024-01-01 12:00:00")
    def test_cache_timestamp(self):
        """Test that cache includes correct timestamp."""
        metadata = get_team_metadata(self.team)

        assert metadata is not None
        self.assertIn("last_updated", metadata)
        # Parse and verify the timestamp
        timestamp = datetime.fromisoformat(metadata["last_updated"])
        self.assertEqual(timestamp.year, 2024)
        self.assertEqual(timestamp.month, 1)
        self.assertEqual(timestamp.day, 1)

    def test_cache_handles_special_fields(self):
        """Test that special fields are properly serialized."""
        # Set some special fields
        self.team.session_recording_sample_rate = 0.5
        self.team.session_recording_opt_in = True
        self.team.capture_console_log_opt_in = False
        self.team.save()

        metadata = get_team_metadata(self.team)

        assert metadata is not None
        # Decimal fields are serialized as floats in JSON
        self.assertEqual(metadata["session_recording_sample_rate"], 0.5)
        self.assertEqual(metadata["session_recording_opt_in"], True)
        self.assertEqual(metadata["capture_console_log_opt_in"], False)

    def test_cache_handles_json_fields(self):
        """Test that JSON fields are properly cached."""
        test_config = {"key": "value", "nested": {"data": 123}}
        self.team.session_replay_config = test_config
        self.team.save()

        metadata = get_team_metadata(self.team)

        assert metadata is not None
        self.assertEqual(metadata["session_replay_config"], test_config)


class TestTeamMetadataCacheTasks(TransactionTestCase):
    """Test Celery tasks for team metadata cache."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        # Team.objects.create will automatically create a project if not provided
        self.team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )
        self.project = self.team.project

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.update_cache")
    def test_update_team_metadata_cache_task(self, mock_update):
        """Test the Celery task for updating a single team's cache."""
        mock_update.return_value = True

        update_team_metadata_cache_task(self.team.id)

        mock_update.assert_called_once()

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.update_cache")
    def test_update_team_metadata_cache_task_nonexistent_team(self, mock_update):
        """Test the task handles non-existent teams gracefully."""
        update_team_metadata_cache_task(999999)  # Non-existent ID

        # Should not attempt to update cache for non-existent team
        mock_update.assert_not_called()

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.update_cache")
    def test_sync_all_team_metadata_cache(self, mock_update):
        """Test the task for syncing all team caches."""
        # Create additional teams
        Team.objects.create(
            organization=self.organization,
            name="Test Team 2",
        )
        Team.objects.create(
            organization=self.organization,
            name="Test Team 3",
        )

        mock_update.return_value = True

        sync_all_team_metadata_cache()

        # Should be called once for each team
        self.assertEqual(mock_update.call_count, 3)

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.update_cache")
    def test_update_team_metadata_cache_batch(self, mock_update):
        """Test batch update task."""
        team2 = Team.objects.create(
            organization=self.organization,
            name="Test Team 2",
        )

        mock_update.return_value = True

        update_team_metadata_cache_batch([self.team.id, team2.id])

        self.assertEqual(mock_update.call_count, 2)

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.update_cache")
    def test_update_team_metadata_cache_batch_with_failures(self, mock_update):
        """Test batch update handles partial failures."""
        team2 = Team.objects.create(
            organization=self.organization,
            name="Test Team 2",
        )

        # First call fails, second succeeds
        mock_update.side_effect = [False, True]

        update_team_metadata_cache_batch([self.team.id, team2.id])

        self.assertEqual(mock_update.call_count, 2)


class TestTeamMetadataCacheSignals(TransactionTestCase):
    """Test Django signals for cache invalidation."""

    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    def test_signal_on_team_create(self, mock_task):
        """Test that creating a team triggers cache update."""
        team = Team.objects.create(
            organization=self.organization,
            name="New Team",
        )

        mock_task.assert_called_once_with(team.id)

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    def test_signal_on_team_update(self, mock_task):
        """Test that updating a team triggers cache update."""
        team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )
        mock_task.reset_mock()

        team.name = "Updated Team"
        team.save()

        mock_task.assert_called_once_with(team.id)

    @patch("posthog.storage.team_metadata_cache.clear_team_metadata_cache")
    def test_signal_on_team_delete(self, mock_clear):
        """Test that deleting a team clears its cache."""
        team = Team.objects.create(
            organization=self.organization,
            name="Test Team",
        )

        team.delete()

        mock_clear.assert_called_once()


class TestIntelligentCacheRefresh(BaseTest):
    """Test intelligent cache refresh functionality."""

    def test_get_teams_needing_refresh_recently_updated(self):
        """Test that recently updated teams are identified for refresh."""
        from datetime import timedelta

        from django.utils import timezone

        from posthog.storage.team_metadata_cache import get_teams_needing_refresh

        # Update a team's updated_at to be recent
        self.team.updated_at = timezone.now() - timedelta(minutes=30)
        self.team.save()

        teams = get_teams_needing_refresh(
            ttl_threshold_hours=24,
            recently_updated_hours=1,
            batch_size=10,
        )

        self.assertIn(self.team.id, [t.id for t in teams])

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_get_teams_needing_refresh_expiring_soon(self, mock_get_client):
        """Test that teams with expiring caches are identified."""
        from posthog.storage.team_metadata_cache import get_teams_needing_refresh

        # Mock Redis client to return low TTL
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            f"cache:team_metadata:team_tokens/{self.team.api_token}/full_metadata.json".encode()
        ]
        mock_redis.ttl.return_value = 3600  # 1 hour left

        teams = get_teams_needing_refresh(
            ttl_threshold_hours=24,  # Should catch 1-hour TTL
            recently_updated_hours=0,  # Ignore recently updated
            batch_size=10,
        )

        self.assertIn(self.team.id, [t.id for t in teams])

    def test_refresh_stale_caches(self):
        """Test the refresh_stale_caches function."""
        from posthog.storage.team_metadata_cache import refresh_stale_caches

        with patch("posthog.storage.team_metadata_cache.get_teams_needing_refresh") as mock_get_teams:
            with patch("posthog.storage.team_metadata_cache.update_team_metadata_cache") as mock_update:
                mock_get_teams.return_value = [self.team]
                mock_update.return_value = True

                successful, failed = refresh_stale_caches()

                self.assertEqual(successful, 1)
                self.assertEqual(failed, 0)
                mock_update.assert_called_once_with(self.team)

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_get_cache_stats(self, mock_get_client):
        """Test cache statistics gathering."""
        from posthog.storage.team_metadata_cache import get_cache_stats

        # Mock Redis client
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.scan_iter.return_value = [
            b"cache:team_metadata:key1",
            b"cache:team_metadata:key2",
            b"cache:team_metadata:key3",
        ]
        mock_redis.ttl.side_effect = [
            86400,  # 1 day
            3600,  # 1 hour
            -1,  # Expired
        ]

        with patch("posthog.models.team.team.Team.objects.count", return_value=10):
            stats = get_cache_stats()

        self.assertEqual(stats["total_cached"], 3)
        self.assertEqual(stats["total_teams"], 10)
        self.assertEqual(stats["ttl_distribution"]["expires_24h"], 1)
        self.assertEqual(stats["ttl_distribution"]["expires_1h"], 1)
        self.assertEqual(stats["ttl_distribution"]["expired"], 1)
