from datetime import datetime, UTC
from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_dual import DualQueryCacheManager


class TestDualQueryCacheManager(APIBaseTest):
    """Test dual query cache manager functionality."""

    def setUp(self):
        super().setUp()
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456
        self.test_response = {"data": "test_data", "columns": ["col1", "col2"]}
        self.target_age = datetime.now(UTC)

    def test_dual_manager_initialization(self):
        """Test dual cache manager initializes with correct parameters."""
        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
            prefer_s3=True,
        )

        self.assertEqual(manager.team_id, self.team.pk)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)
        self.assertTrue(manager.prefer_s3)
        self.assertIsNotNone(manager.s3_cache)
        self.assertIsNotNone(manager.django_cache)

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.set_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.set_cache_data")
    def test_set_cache_data_writes_to_both(self, mock_django_set, mock_s3_set):
        """Test that set_cache_data writes to both S3 and Django cache."""
        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        manager.set_cache_data(response=self.test_response, target_age=self.target_age)

        mock_s3_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)
        mock_django_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.set_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.set_cache_data")
    def test_set_cache_data_handles_s3_failure(self, mock_django_set, mock_s3_set):
        """Test that set_cache_data handles S3 failure gracefully."""
        mock_s3_set.side_effect = Exception("S3 error")

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        manager.set_cache_data(response=self.test_response, target_age=self.target_age)

        mock_s3_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)
        mock_django_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.set_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.set_cache_data")
    def test_set_cache_data_handles_django_failure(self, mock_django_set, mock_s3_set):
        """Test that set_cache_data handles Django cache failure gracefully."""
        mock_django_set.side_effect = Exception("Django cache error")

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        manager.set_cache_data(response=self.test_response, target_age=self.target_age)

        mock_s3_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)
        mock_django_set.assert_called_once_with(response=self.test_response, target_age=self.target_age)

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.set_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.set_cache_data")
    def test_set_cache_data_raises_when_both_fail(self, mock_django_set, mock_s3_set):
        """Test that set_cache_data raises exception when both caches fail."""
        mock_s3_set.side_effect = Exception("S3 error")
        mock_django_set.side_effect = Exception("Django cache error")

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        with self.assertRaises(Exception) as context:
            manager.set_cache_data(response=self.test_response, target_age=self.target_age)

        self.assertIn("Failed to write to both S3 and Django cache", str(context.exception))

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_prefers_s3_when_enabled(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data prefers S3 when prefer_s3 is True."""
        mock_s3_get.return_value = self.test_response

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        result = manager.get_cache_data()

        self.assertEqual(result, self.test_response)
        mock_s3_get.assert_called_once()
        mock_django_get.assert_not_called()

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_prefers_django_when_s3_disabled(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data prefers Django cache when prefer_s3 is False."""
        mock_django_get.return_value = self.test_response

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=False,
        )

        result = manager.get_cache_data()

        self.assertEqual(result, self.test_response)
        mock_django_get.assert_called_once()
        mock_s3_get.assert_not_called()

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_fallback_from_s3_to_django(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data falls back to Django when S3 fails."""
        mock_s3_get.return_value = None  # S3 cache miss
        mock_django_get.return_value = self.test_response

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        result = manager.get_cache_data()

        self.assertEqual(result, self.test_response)
        mock_s3_get.assert_called_once()
        mock_django_get.assert_called_once()

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_fallback_from_django_to_s3(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data falls back to S3 when Django cache fails."""
        mock_django_get.return_value = None  # Django cache miss
        mock_s3_get.return_value = self.test_response

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=False,
        )

        result = manager.get_cache_data()

        self.assertEqual(result, self.test_response)
        mock_django_get.assert_called_once()
        mock_s3_get.assert_called_once()

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_exception_fallback(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data handles exceptions and falls back properly."""
        mock_s3_get.side_effect = Exception("S3 error")
        mock_django_get.return_value = self.test_response

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        result = manager.get_cache_data()

        self.assertEqual(result, self.test_response)
        mock_s3_get.assert_called_once()
        mock_django_get.assert_called_once()

    @patch("posthog.hogql_queries.query_cache_dual.S3QueryCacheManager.get_cache_data")
    @patch("posthog.hogql_queries.query_cache_dual.DjangoCacheQueryCacheManager.get_cache_data")
    def test_get_cache_data_returns_none_when_both_fail(self, mock_django_get, mock_s3_get):
        """Test that get_cache_data returns None when both caches fail."""
        mock_s3_get.return_value = None
        mock_django_get.return_value = None

        manager = DualQueryCacheManager(
            team_id=self.team.pk,
            cache_key=self.cache_key,
            prefer_s3=True,
        )

        result = manager.get_cache_data()

        self.assertIsNone(result)
        mock_s3_get.assert_called_once()
        mock_django_get.assert_called_once()
