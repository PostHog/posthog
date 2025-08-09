from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager


class TestQueryCacheFactory(APIBaseTest):
    """Test query cache manager factory functionality."""

    def setUp(self):
        super().setUp()
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3", return_value=False)
    def test_get_redis_cache_manager_default(self, mock_feature_flag):
        """Test factory returns Redis manager by default."""

        manager = get_query_cache_manager(
            team=self.team,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, DjangoCacheQueryCacheManager)
        self.assertEqual(manager.team_id, self.team.pk)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3", return_value=True)
    def test_get_s3_cache_manager(self, mock_feature_flag):
        """Test factory returns S3 manager when feature flag is enabled."""

        manager = get_query_cache_manager(
            team=self.team,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, S3QueryCacheManager)
        self.assertEqual(manager.team_id, self.team.pk)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)
