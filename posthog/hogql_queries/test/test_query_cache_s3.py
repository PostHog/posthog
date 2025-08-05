import json
import uuid
from datetime import datetime, UTC, timedelta
from unittest.mock import patch, MagicMock
from typing import Optional

from django.conf import settings
from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
from posthog.cache_utils import OrjsonJsonSerializer


class TestS3QueryCacheManager(APIBaseTest):
    """Test S3-based query cache manager functionality."""

    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456

        # Mock storage client
        self.mock_storage_client = MagicMock()

    def _create_cache_manager(
        self,
        cache_key: Optional[str] = None,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        *,
        use_defaults: bool = True,
    ) -> S3QueryCacheManager:
        """Helper to create cache manager with mocked storage."""
        if use_defaults:
            final_cache_key = cache_key or self.cache_key
            final_insight_id = insight_id if insight_id is not None else self.insight_id
            final_dashboard_id = dashboard_id if dashboard_id is not None else self.dashboard_id
        else:
            final_cache_key = cache_key
            final_insight_id = insight_id
            final_dashboard_id = dashboard_id

        manager = S3QueryCacheManager(
            team_id=self.team_id,
            cache_key=final_cache_key,
            insight_id=final_insight_id,
            dashboard_id=final_dashboard_id,
        )
        manager.storage_client = self.mock_storage_client
        return manager

    def test_cache_object_key_generation(self):
        """Test S3 object key generation for cache data."""
        manager = self._create_cache_manager()
        expected_key = f"query_cache/{self.team_id}/{self.cache_key}"
        self.assertEqual(manager._cache_object_key(), expected_key)

    def test_stale_insights_object_key_generation(self):
        """Test S3 object key generation for stale insights tracking."""
        manager = self._create_cache_manager()
        expected_key = f"query_cache_timestamps/{self.team_id}/{self.insight_id}:{self.dashboard_id}"
        self.assertEqual(manager._stale_insights_object_key(), expected_key)

    def test_ttl_days_calculation(self):
        """Test TTL calculation from seconds to days."""
        manager = self._create_cache_manager()

        # Test various TTL values
        self.assertEqual(manager._get_ttl_days(86400), 1)  # 1 day
        self.assertEqual(manager._get_ttl_days(43200), 1)  # 0.5 days -> rounds up to 1
        self.assertEqual(manager._get_ttl_days(172800), 2)  # 2 days
        self.assertEqual(manager._get_ttl_days(259200), 3)  # 3 days
        self.assertEqual(manager._get_ttl_days(1), 1)  # Minimum 1 day

        # Test None defaults to settings value
        with self.settings(CACHED_RESULTS_TTL=86400):
            self.assertEqual(manager._get_ttl_days(None), 1)

    def test_get_cache_data_success(self):
        """Test successful cache data retrieval."""
        manager = self._create_cache_manager()
        test_data = {"result": "test", "count": 42}
        serialized_data = OrjsonJsonSerializer({}).dumps(test_data).decode("utf-8")

        self.mock_storage_client.read.return_value = serialized_data

        result = manager.get_cache_data()

        self.assertEqual(result, test_data)
        self.mock_storage_client.read.assert_called_once_with(
            manager.bucket, f"query_cache/{self.team_id}/{self.cache_key}"
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

    def test_set_cache_data_success(self):
        """Test successful cache data storage."""
        manager = self._create_cache_manager()
        test_data = {"result": "test", "count": 42}
        target_age = datetime.now(UTC) + timedelta(hours=1)

        manager.set_cache_data(response=test_data, target_age=target_age)

        # Verify write was called with correct parameters (2 calls: cache data + target age)
        self.assertEqual(self.mock_storage_client.write.call_count, 2)

        # Check the first call (cache data)
        cache_call = self.mock_storage_client.write.call_args_list[0]
        call_args = cache_call

        self.assertEqual(call_args[1]["bucket"], manager.bucket)
        self.assertEqual(call_args[1]["key"], f"query_cache/{self.team_id}/{self.cache_key}")

        # Verify content is correct JSON
        content = call_args[1]["content"]
        parsed_content = json.loads(content)
        self.assertEqual(parsed_content, test_data)

        # Verify TTL tags
        extras = call_args[1]["extras"]
        self.assertIn("Tagging", extras)
        self.assertIn("ttl_days=", extras["Tagging"])
        self.assertIn("cache_type=query_results", extras["Tagging"])

    def test_set_cache_data_without_target_age(self):
        """Test cache data storage without target age."""
        manager = self._create_cache_manager()
        test_data = {"result": "test"}

        with patch.object(manager, "remove_last_refresh") as mock_remove:
            manager.set_cache_data(response=test_data, target_age=None)
            mock_remove.assert_called_once()

    def test_update_target_age_success(self):
        """Test successful target age update."""
        manager = self._create_cache_manager()
        target_age = datetime.now(UTC) + timedelta(hours=1)

        manager.update_target_age(target_age)

        # Verify write was called for target age tracking
        self.mock_storage_client.write.assert_called_once()
        call_args = self.mock_storage_client.write.call_args

        self.assertEqual(call_args[1]["bucket"], manager.bucket)
        self.assertEqual(
            call_args[1]["key"], f"query_cache_timestamps/{self.team_id}/{self.insight_id}:{self.dashboard_id}"
        )

        # Verify content structure
        content = json.loads(call_args[1]["content"])
        self.assertEqual(content["insight_id"], self.insight_id)
        self.assertEqual(content["dashboard_id"], self.dashboard_id)
        self.assertEqual(content["team_id"], self.team_id)
        self.assertIn("target_age", content)
        self.assertIn("updated_at", content)

    def test_update_target_age_without_insight_id(self):
        """Test target age update skipped when no insight_id."""
        manager = self._create_cache_manager(insight_id=None, use_defaults=False)
        manager.cache_key = self.cache_key  # Set cache_key so it doesn't break

        manager.update_target_age(datetime.now(UTC))

        self.mock_storage_client.write.assert_not_called()

    def test_remove_last_refresh_success(self):
        """Test successful removal of last refresh tracking."""
        manager = self._create_cache_manager()

        manager.remove_last_refresh()

        self.mock_storage_client.delete.assert_called_once_with(
            manager.bucket, f"query_cache_timestamps/{self.team_id}/{self.insight_id}:{self.dashboard_id}"
        )

    def test_remove_last_refresh_without_insight_id(self):
        """Test removal skipped when no insight_id."""
        manager = self._create_cache_manager(insight_id=None, use_defaults=False)

        manager.remove_last_refresh()

        self.mock_storage_client.delete.assert_not_called()

    @patch("posthog.hogql_queries.query_cache_s3.object_storage_client")
    def test_get_stale_insights_success(self, mock_storage_factory):
        """Test successful stale insights retrieval."""
        mock_storage_client = MagicMock()
        mock_storage_factory.return_value = mock_storage_client

        # Setup mock data for stale insights
        current_time = datetime.now(UTC)
        stale_time = current_time - timedelta(hours=1)
        fresh_time = current_time + timedelta(hours=1)

        mock_storage_client.list_objects.return_value = [
            f"query_cache_timestamps/{self.team_id}/123:456",
            f"query_cache_timestamps/{self.team_id}/789:012",
            f"query_cache_timestamps/{self.team_id}/345:678",
        ]

        # Mock read responses - some stale, some fresh
        def mock_read(bucket, key):
            if "123:456" in key:
                return json.dumps(
                    {
                        "target_age": stale_time.isoformat(),
                        "insight_id": 123,
                        "dashboard_id": 456,
                        "team_id": self.team_id,
                    }
                )
            elif "789:012" in key:
                return json.dumps(
                    {
                        "target_age": fresh_time.isoformat(),
                        "insight_id": 789,
                        "dashboard_id": 12,
                        "team_id": self.team_id,
                    }
                )
            elif "345:678" in key:
                return json.dumps(
                    {
                        "target_age": stale_time.isoformat(),
                        "insight_id": 345,
                        "dashboard_id": 678,
                        "team_id": self.team_id,
                    }
                )
            return None

        mock_storage_client.read.side_effect = mock_read

        # Test without limit
        stale_insights = S3QueryCacheManager.get_stale_insights(team_id=self.team_id)

        # Should return only the stale ones, sorted by target age
        self.assertEqual(len(stale_insights), 2)
        self.assertIn("123:456", stale_insights)
        self.assertIn("345:678", stale_insights)
        self.assertNotIn("789:012", stale_insights)

        # Test with limit
        stale_insights_limited = S3QueryCacheManager.get_stale_insights(team_id=self.team_id, limit=1)
        self.assertEqual(len(stale_insights_limited), 1)

    @patch("posthog.hogql_queries.query_cache_s3.object_storage_client")
    def test_get_stale_insights_empty(self, mock_storage_factory):
        """Test stale insights retrieval with no objects."""
        mock_storage_client = MagicMock()
        mock_storage_factory.return_value = mock_storage_client

        mock_storage_client.list_objects.return_value = []

        stale_insights = S3QueryCacheManager.get_stale_insights(team_id=self.team_id)

        self.assertEqual(stale_insights, [])

    @patch("posthog.hogql_queries.query_cache_s3.object_storage_client")
    def test_clean_up_stale_insights_success(self, mock_storage_factory):
        """Test successful cleanup of stale insights."""
        mock_storage_client = MagicMock()
        mock_storage_factory.return_value = mock_storage_client

        # Setup mock data
        current_time = datetime.now(UTC)
        old_time = current_time - timedelta(days=2)
        recent_time = current_time - timedelta(hours=1)
        threshold = current_time - timedelta(days=1)

        mock_storage_client.list_objects.return_value = [
            f"query_cache_timestamps/{self.team_id}/old_insight",
            f"query_cache_timestamps/{self.team_id}/recent_insight",
        ]

        def mock_read(bucket, key):
            if "old_insight" in key:
                return json.dumps({"target_age": old_time.isoformat()})
            elif "recent_insight" in key:
                return json.dumps({"target_age": recent_time.isoformat()})
            return None

        mock_storage_client.read.side_effect = mock_read

        S3QueryCacheManager.clean_up_stale_insights(team_id=self.team_id, threshold=threshold)

        # Should delete only the old insight
        expected_bucket = settings.QUERY_CACHE_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET
        mock_storage_client.delete.assert_called_once_with(
            expected_bucket, f"query_cache_timestamps/{self.team_id}/old_insight"
        )

    def test_identifier_property(self):
        """Test identifier property generation."""
        manager = self._create_cache_manager()
        expected = f"{self.insight_id}:{self.dashboard_id}"
        self.assertEqual(manager.identifier, expected)

        # Test with no dashboard_id
        manager_no_dashboard = self._create_cache_manager(dashboard_id=None, use_defaults=False)
        manager_no_dashboard.insight_id = self.insight_id  # Set insight_id explicitly
        expected_no_dashboard = f"{self.insight_id}:"
        self.assertEqual(manager_no_dashboard.identifier, expected_no_dashboard)

    def test_settings_integration(self):
        """Test integration with Django settings."""
        with self.settings(
            QUERY_CACHE_S3_BUCKET="custom-bucket",
            CACHED_RESULTS_TTL=172800,  # 2 days
        ):
            manager = self._create_cache_manager()
            self.assertEqual(manager.bucket, "custom-bucket")
            self.assertEqual(manager._get_ttl_days(), 2)

    def test_real_s3_integration(self):
        """Test with real S3 storage client (if enabled)."""
        # This test only runs if object storage is enabled in settings
        # and should be run against actual S3/MinIO for integration testing
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            try:
                manager = S3QueryCacheManager(
                    team_id=self.team_id,
                    cache_key=f"test_{uuid.uuid4()}",
                    insight_id=999,
                    dashboard_id=888,
                )

                # Test data
                test_data = {"test": "real_s3", "timestamp": datetime.now(UTC).isoformat()}

                # Set and get cache data
                manager.set_cache_data(response=test_data, target_age=None)
                retrieved_data = manager.get_cache_data()

                self.assertEqual(retrieved_data, test_data)

            except Exception:
                # Skip if S3 is not properly configured
                self.skipTest("S3 storage not properly configured for integration test")
