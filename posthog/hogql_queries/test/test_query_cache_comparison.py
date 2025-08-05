"""
Integration tests comparing Redis and S3 query cache implementations.
Tests ensure both backends provide equivalent functionality.
"""

import uuid
from datetime import datetime, UTC, timedelta
from unittest.mock import patch, MagicMock

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager


class TestQueryCacheComparison(APIBaseTest):
    """Compare Redis and S3 query cache implementations."""

    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.cache_key = f"test_cache_key_{uuid.uuid4()}"
        self.insight_id = 123
        self.dashboard_id = 456
        self.test_data = {
            "results": [{"count": 42, "breakdown": "test"}],
            "columns": ["count", "breakdown"],
            "meta": {"total": 42},
        }

    def _create_django_cache_manager(self) -> DjangoCacheQueryCacheManager:
        """Create Django cache manager."""
        return DjangoCacheQueryCacheManager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

    def _create_s3_manager(self, mock_storage: bool = True) -> S3QueryCacheManager:
        """Create S3 cache manager with optional storage mocking."""
        manager = S3QueryCacheManager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        if mock_storage:
            # Mock the storage client to avoid actual S3 calls
            manager.storage_client = MagicMock()
            # Store data in memory for consistent testing
            manager._memory_storage = {}

            def mock_read(bucket, key):
                return manager._memory_storage.get(key)

            def mock_write(bucket, key, content, extras=None):
                manager._memory_storage[key] = content

            def mock_delete(bucket, key):
                manager._memory_storage.pop(key, None)

            def mock_list_objects(bucket, prefix):
                return [k for k in manager._memory_storage.keys() if k.startswith(prefix)]

            manager.storage_client.read.side_effect = mock_read
            manager.storage_client.write.side_effect = mock_write
            manager.storage_client.delete.side_effect = mock_delete
            manager.storage_client.list_objects.side_effect = mock_list_objects

        return manager

    def test_cache_data_operations_consistency(self):
        """Test cache data set/get operations are consistent between backends."""
        django_cache_manager = self._create_django_cache_manager()
        s3_manager = self._create_s3_manager()

        # Both should return None initially
        self.assertIsNone(django_cache_manager.get_cache_data())
        self.assertIsNone(s3_manager.get_cache_data())

        # Set data in both
        target_age = datetime.now(UTC) + timedelta(hours=1)
        django_cache_manager.set_cache_data(response=self.test_data, target_age=target_age)
        s3_manager.set_cache_data(response=self.test_data, target_age=target_age)

        # Both should return the same data
        django_cache_result = django_cache_manager.get_cache_data()
        s3_result = s3_manager.get_cache_data()

        self.assertEqual(django_cache_result, self.test_data)
        self.assertEqual(s3_result, self.test_data)
        self.assertEqual(django_cache_result, s3_result)

    def test_identifier_property_consistency(self):
        """Test identifier property is consistent between backends."""
        django_cache_manager = self._create_django_cache_manager()
        s3_manager = self._create_s3_manager()

        self.assertEqual(django_cache_manager.identifier, s3_manager.identifier)
        self.assertEqual(django_cache_manager.identifier, f"{self.insight_id}:{self.dashboard_id}")

    def test_target_age_operations_consistency(self):
        """Test target age operations are consistent between backends."""
        django_cache_manager = self._create_django_cache_manager()
        s3_manager = self._create_s3_manager()

        target_age = datetime.now(UTC) + timedelta(hours=2)

        # Update target age in both
        django_cache_manager.update_target_age(target_age)
        s3_manager.update_target_age(target_age)

        # Remove from both
        django_cache_manager.remove_last_refresh()
        s3_manager.remove_last_refresh()

        # Both operations should complete without errors
        # Specific validation would require accessing internal state

    def test_stale_insights_interface_consistency(self):
        """Test stale insights static methods have consistent interface."""
        # Both should have the same static method signatures
        django_cache_stale = DjangoCacheQueryCacheManager.get_stale_insights(team_id=self.team_id)
        s3_stale = S3QueryCacheManager.get_stale_insights(team_id=self.team_id)

        # Both should return lists
        self.assertIsInstance(django_cache_stale, list)
        self.assertIsInstance(s3_stale, list)

        # Both should accept limit parameter
        django_cache_limited = DjangoCacheQueryCacheManager.get_stale_insights(team_id=self.team_id, limit=5)
        s3_limited = S3QueryCacheManager.get_stale_insights(team_id=self.team_id, limit=5)

        self.assertIsInstance(django_cache_limited, list)
        self.assertIsInstance(s3_limited, list)

    def test_cleanup_interface_consistency(self):
        """Test cleanup static methods have consistent interface."""
        threshold = datetime.now(UTC) - timedelta(days=1)

        # Both should accept the same parameters without errors
        DjangoCacheQueryCacheManager.clean_up_stale_insights(team_id=self.team_id, threshold=threshold)
        S3QueryCacheManager.clean_up_stale_insights(team_id=self.team_id, threshold=threshold)

    def test_none_insight_id_handling_consistency(self):
        """Test both backends handle None insight_id consistently."""
        django_cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=None,
            dashboard_id=self.dashboard_id,
        )

        s3_manager = self._create_s3_manager()
        s3_manager.insight_id = None

        # Both should handle None insight_id gracefully
        target_age = datetime.now(UTC) + timedelta(hours=1)

        # These should not raise errors
        django_cache_manager.update_target_age(target_age)
        django_cache_manager.remove_last_refresh()

        s3_manager.update_target_age(target_age)
        s3_manager.remove_last_refresh()

    def test_error_handling_consistency(self):
        """Test both backends handle errors consistently."""
        django_cache_manager = self._create_django_cache_manager()
        s3_manager = self._create_s3_manager()

        # Mock Redis to raise an exception
        with patch.object(django_cache_manager, "redis_client") as mock_redis:
            mock_redis.get.side_effect = Exception("Redis error")
            django_cache_result = django_cache_manager.get_cache_data()

        # Mock S3 to raise an exception
        s3_manager.storage_client.read.side_effect = Exception("S3 error")
        s3_result = s3_manager.get_cache_data()

        # Both should handle errors gracefully and return None
        self.assertIsNone(django_cache_result)
        self.assertIsNone(s3_result)

    def test_cache_key_isolation(self):
        """Test cache key isolation between different instances."""
        # Create managers with different cache keys
        django_cache_manager1 = DjangoCacheQueryCacheManager(
            team_id=self.team_id,
            cache_key="key1",
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        django_cache_manager2 = DjangoCacheQueryCacheManager(
            team_id=self.team_id,
            cache_key="key2",
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        s3_manager1 = self._create_s3_manager()
        s3_manager1.cache_key = "key1"

        s3_manager2 = self._create_s3_manager()
        s3_manager2.cache_key = "key2"

        # Set different data in each
        data1 = {"test": "data1"}
        data2 = {"test": "data2"}

        django_cache_manager1.set_cache_data(response=data1, target_age=None)
        django_cache_manager2.set_cache_data(response=data2, target_age=None)

        s3_manager1.set_cache_data(response=data1, target_age=None)
        s3_manager2.set_cache_data(response=data2, target_age=None)

        # Verify isolation
        self.assertEqual(django_cache_manager1.get_cache_data(), data1)
        self.assertEqual(django_cache_manager2.get_cache_data(), data2)

        self.assertEqual(s3_manager1.get_cache_data(), data1)
        self.assertEqual(s3_manager2.get_cache_data(), data2)
