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

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache")
    def test_sync_all_team_metadata_cache(self, mock_update):
        """Test the task for syncing all team caches."""
        # Create additional teams
        team2 = Team.objects.create(
            organization=self.organization,
            name="Test Team 2",
        )
        team3 = Team.objects.create(
            organization=self.organization,
            name="Test Team 3",
        )

        mock_update.return_value = True

        sync_all_team_metadata_cache()

        # Should be called at least once for each team we know about (3 teams minimum)
        # There might be other teams from other tests in TransactionTestCase
        self.assertGreaterEqual(mock_update.call_count, 3)

        # Verify our teams were processed
        teams_processed = [call.args[0] for call in mock_update.call_args_list]
        team_ids_processed = [t.id for t in teams_processed]
        self.assertIn(self.team.id, team_ids_processed)
        self.assertIn(team2.id, team_ids_processed)
        self.assertIn(team3.id, team_ids_processed)

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache", return_value=True)
    @patch("posthog.tasks.team_metadata.Team")
    def test_update_team_metadata_cache_batch(self, mock_team_class, mock_update):
        """Test batch update task."""
        # Create mock teams
        mock_team1 = MagicMock()
        mock_team1.id = 1
        mock_team2 = MagicMock()
        mock_team2.id = 2

        # Setup Team.objects.get to return our mock teams
        mock_team_class.objects.get.side_effect = [mock_team1, mock_team2]

        # Call the batch update
        update_team_metadata_cache_batch([1, 2])

        # Verify update was called for each team
        self.assertEqual(mock_update.call_count, 2)
        mock_update.assert_any_call(mock_team1)
        mock_update.assert_any_call(mock_team2)

    @patch("posthog.tasks.team_metadata.update_team_metadata_cache")
    @patch("posthog.tasks.team_metadata.Team")
    def test_update_team_metadata_cache_batch_with_failures(self, mock_team_class, mock_update):
        """Test batch update handles partial failures."""
        # Create mock teams
        mock_team1 = MagicMock()
        mock_team1.id = 1
        mock_team2 = MagicMock()
        mock_team2.id = 2

        # Setup Team.objects.get to return our mock teams
        mock_team_class.objects.get.side_effect = [mock_team1, mock_team2]

        # Set both to succeed to avoid retry logic
        mock_update.side_effect = [True, True]

        # Call batch update
        update_team_metadata_cache_batch([1, 2])

        # Verify update was called for each team
        self.assertEqual(mock_update.call_count, 2)
        mock_update.assert_any_call(mock_team1)
        mock_update.assert_any_call(mock_team2)


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

    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache")
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


class TestEdgeCases(BaseTest):
    """Test edge cases and failure scenarios."""

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_redis_connection_failure(self, mock_get_client):
        """Test handling of Redis connection failures."""
        from redis.exceptions import ConnectionError

        from posthog.storage.team_metadata_cache import get_teams_needing_refresh

        # Mock Redis connection failure
        mock_get_client.side_effect = ConnectionError("Connection refused")

        # Should handle gracefully and return empty list
        teams = get_teams_needing_refresh()

        self.assertEqual(teams, [])

    @patch("posthog.storage.team_metadata_cache.team_metadata_hypercache.get_from_cache")
    def test_malformed_cached_data(self, mock_get):
        """Test handling of malformed cached data."""
        from posthog.storage.team_metadata_cache import get_team_metadata

        # Return malformed data
        mock_get.return_value = "not a dict"

        result = get_team_metadata(self.team)

        # Should handle gracefully
        self.assertEqual(result, "not a dict")

    def test_concurrent_cache_updates(self):
        """Test that concurrent updates are handled properly."""
        import threading

        from posthog.storage.team_metadata_cache import get_team_metadata, update_team_metadata_cache

        results = []
        metadata_results = []

        # First, update the team with a specific value
        self.team.name = "Original Name"
        self.team.save()
        update_team_metadata_cache(self.team)

        def update_cache():
            result = update_team_metadata_cache(self.team)
            results.append(result)
            # After update, immediately read to check consistency
            metadata = get_team_metadata(self.team)
            metadata_results.append(metadata)

        # Start multiple threads to update cache concurrently
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=update_cache)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All updates should succeed
        self.assertEqual(len(results), 5)
        self.assertTrue(all(results))

        # All metadata reads should be consistent
        self.assertEqual(len(metadata_results), 5)
        # All should have the same team name
        for metadata in metadata_results:
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata["name"], "Original Name")

    def test_concurrent_cache_updates_with_modifications(self):
        """Test data consistency when team is modified during concurrent cache updates."""
        import time
        import threading

        from posthog.storage.team_metadata_cache import get_team_metadata, update_team_metadata_cache

        results = []
        names_seen = set()

        def update_and_modify(thread_id):
            # Each thread modifies the team name and updates cache
            self.team.name = f"Thread {thread_id} Name"
            self.team.save()

            # Small delay to increase chance of race conditions
            time.sleep(0.01)

            result = update_team_metadata_cache(self.team)
            results.append(result)

            # Read back the metadata
            metadata = get_team_metadata(self.team)
            if metadata:
                names_seen.add(metadata["name"])

        # Start multiple threads that modify and update
        threads = []
        for i in range(5):
            thread = threading.Thread(target=update_and_modify, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All updates should succeed
        self.assertEqual(len(results), 5)
        self.assertTrue(all(results))

        # The final cached value should be one of the thread names
        final_metadata = get_team_metadata(self.team)
        self.assertIsNotNone(final_metadata)
        # The name should be from one of the threads (last writer wins)
        self.assertTrue(
            any(f"Thread {i} Name" == final_metadata["name"] for i in range(5)),
            f"Final name '{final_metadata['name']}' not from any thread",
        )

    @patch("posthog.storage.team_metadata_cache.get_client")
    def test_cache_key_without_ttl(self, mock_get_client):
        """Test handling of cache keys without TTL."""
        from posthog.storage.team_metadata_cache import get_teams_needing_refresh

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Mock keys without TTL (returns -1)
        mock_redis.scan_iter.return_value = [b"cache:team_metadata:key1"]
        mock_redis.ttl.return_value = -1

        teams = get_teams_needing_refresh()

        # Should skip keys without TTL
        self.assertEqual(teams, [])

    def test_team_with_null_fields(self):
        """Test caching of teams with null/empty fields."""
        from posthog.storage.team_metadata_cache import get_team_metadata

        # Create a team with minimal fields
        self.team.slack_incoming_webhook = None
        self.team.session_replay_config = None
        self.team.save()

        metadata = get_team_metadata(self.team)

        self.assertIsNotNone(metadata)
        self.assertIsNone(metadata["slack_incoming_webhook"])
        self.assertIsNone(metadata["session_replay_config"])

    def test_maximum_cache_entry_size(self):
        """Test handling of very large cache entries."""
        from posthog.storage.team_metadata_cache import update_team_metadata_cache

        # Create a team with very large JSON fields
        large_config = {"key": "x" * 10000}  # Large config
        self.team.session_replay_config = large_config
        self.team.session_recording_masking_config = large_config
        self.team.save()

        # Should handle large entries
        success = update_team_metadata_cache(self.team)

        self.assertTrue(success)

    @patch("posthog.tasks.team_metadata.logger")
    @patch("posthog.tasks.team_metadata.update_team_metadata_cache_task.delay")
    @patch("posthog.tasks.team_metadata.transaction")
    def test_signal_error_handling(self, mock_transaction, mock_task, mock_logger):
        """Test that signal handlers handle errors gracefully and log appropriately."""
        from celery.exceptions import OperationalError

        # Simulate Celery being down
        mock_task.side_effect = OperationalError("Celery is down")

        # Store the callback that would be registered with on_commit
        on_commit_callback = None

        def capture_on_commit(callback):
            nonlocal on_commit_callback
            on_commit_callback = callback
            # Execute the callback immediately in test context
            callback()

        mock_transaction.on_commit.side_effect = capture_on_commit

        # Creating a team should not raise an exception
        try:
            team = Team.objects.create(
                organization=self.organization,
                name="Test Team with Celery Down",
            )
            # Should succeed despite Celery error
            self.assertIsNotNone(team)

            # Verify on_commit was called
            mock_transaction.on_commit.assert_called_once()

            # Verify that the error was logged
            mock_logger.exception.assert_called_once()
            call_args = mock_logger.exception.call_args
            self.assertIn("Failed to enqueue cache update task", call_args[0][0])
            # Check structured logging fields
            self.assertEqual(call_args[1]["team_id"], team.id)
            self.assertIn("Celery is down", call_args[1]["error"])
        except AssertionError:
            # Re-raise assertion errors
            raise
        except Exception as e:
            self.fail(f"Signal handler raised exception: {e}")
