"""
Simplified S3 Query Cache Manager tests focusing on S3-specific functionality.
"""

from datetime import datetime, UTC, timedelta
from unittest.mock import patch, MagicMock

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
from posthog.cache_utils import OrjsonJsonSerializer


class TestS3QueryCacheManagerSimple(APIBaseTest):
    """Test S3-based query cache manager S3-specific functionality."""

    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456
        self.mock_storage_client = MagicMock()

    def _create_cache_manager(
        self,
        cache_key=None,
        insight_id=None,
        dashboard_id=None,
    ) -> S3QueryCacheManager:
        """Create cache manager with mocked storage client."""
        manager = S3QueryCacheManager(
            team_id=self.team_id,
            cache_key=cache_key or self.cache_key,
            insight_id=insight_id or self.insight_id,
            dashboard_id=dashboard_id or self.dashboard_id,
        )
        manager.storage_client = self.mock_storage_client
        return manager

    def test_cache_object_key_generation(self):
        """Test S3 object key generation for cache data."""
        manager = self._create_cache_manager()
        expected_key = f"query_cache/{self.team_id}/{self.cache_key}"
        self.assertEqual(manager._cache_object_key(), expected_key)

    def test_ttl_days_calculation(self):
        """Test TTL calculation from seconds to days."""
        manager = self._create_cache_manager()

        # Test various TTL values
        self.assertEqual(manager._calculate_ttl_days(86400), 1)  # 1 day
        self.assertEqual(manager._calculate_ttl_days(43200), 1)  # 0.5 days -> rounds up to 1
        self.assertEqual(manager._calculate_ttl_days(172800), 2)  # 2 days
        self.assertEqual(manager._calculate_ttl_days(259200), 3)  # 3 days
        self.assertEqual(manager._calculate_ttl_days(1), 1)  # Minimum 1 day

    def test_get_cache_data_success(self):
        """Test successful cache data retrieval."""
        manager = self._create_cache_manager()
        test_data = {"result": "test", "count": 42}
        serialized_data = OrjsonJsonSerializer({}).dumps(test_data).decode("utf-8")

        self.mock_storage_client.read.return_value = serialized_data

        result = manager.get_cache_data()

        self.assertEqual(result, test_data)
        self.mock_storage_client.read.assert_called_once_with(
            bucket=manager.bucket, key=f"query_cache/{self.team_id}/{self.cache_key}"
        )

    def test_get_cache_data_not_found(self):
        """Test cache data retrieval when object doesn't exist."""
        manager = self._create_cache_manager()
        self.mock_storage_client.read.return_value = None

        result = manager.get_cache_data()

        self.assertIsNone(result)

    def test_get_cache_data_error_handling(self):
        """Test cache data retrieval with storage errors."""
        manager = self._create_cache_manager()
        self.mock_storage_client.read.side_effect = Exception("S3 error")

        result = manager.get_cache_data()

        self.assertIsNone(result)

    @patch("posthog.hogql_queries.query_cache_s3.settings")
    def test_set_cache_data_success(self, mock_settings):
        """Test successful cache data storage."""
        mock_settings.CACHED_RESULTS_TTL = 86400  # 1 day
        mock_settings.QUERY_CACHE_S3_BUCKET = "test-bucket"
        mock_settings.OBJECT_STORAGE_BUCKET = "fallback-bucket"

        manager = self._create_cache_manager()
        test_data = {"result": "test", "count": 42}
        target_age = datetime.now(UTC) + timedelta(hours=1)

        with patch.object(manager, "update_target_age") as mock_update:
            manager.set_cache_data(response=test_data, target_age=target_age)

            # Verify S3 write was called
            self.mock_storage_client.write.assert_called_once()
            call_args = self.mock_storage_client.write.call_args

            # Check the call was made with correct arguments
            self.assertEqual(call_args.kwargs["bucket"], manager.bucket)
            self.assertEqual(call_args.kwargs["key"], f"query_cache/{self.team_id}/{self.cache_key}")

            # Check tags include TTL
            extras = call_args.kwargs["extras"]
            self.assertIn("Tagging", extras)
            self.assertIn("ttl_days=1", extras["Tagging"])
            self.assertIn("cache_type=query_data", extras["Tagging"])

            # Verify target age update was called
            mock_update.assert_called_once_with(target_age)

    def test_identifier_property(self):
        """Test identifier property generation."""
        manager = self._create_cache_manager()
        expected_identifier = f"{self.insight_id}:{self.dashboard_id}"
        self.assertEqual(manager.identifier, expected_identifier)

    @patch("posthog.redis.get_client")
    def test_stale_insights_uses_redis(self, mock_redis_client):
        """Test that stale insights tracking uses Redis (inherited from base class)."""
        mock_redis = MagicMock()
        mock_redis_client.return_value = mock_redis
        mock_redis.zrevrangebyscore.return_value = [b"123:456", b"789:012"]

        stale_insights = S3QueryCacheManager.get_stale_insights(team_id=self.team_id, limit=5)

        self.assertEqual(len(stale_insights), 2)
        self.assertIn("123:456", stale_insights)
        self.assertIn("789:012", stale_insights)
        mock_redis.zrevrangebyscore.assert_called_once()

    @patch("posthog.redis.get_client")
    def test_cleanup_stale_insights_uses_redis(self, mock_redis_client):
        """Test that cleanup uses Redis (inherited from base class)."""
        mock_redis = MagicMock()
        mock_redis_client.return_value = mock_redis

        threshold = datetime.now(UTC) - timedelta(days=7)
        S3QueryCacheManager.clean_up_stale_insights(team_id=self.team_id, threshold=threshold)

        mock_redis.zremrangebyscore.assert_called_once_with(
            f"cache_timestamps:{self.team_id}", "-inf", threshold.timestamp()
        )
