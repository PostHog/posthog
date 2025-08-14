from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_cache_dual import DualQueryCacheManager


class TestQueryCacheFactory(APIBaseTest):
    """Test query cache manager factory functionality."""

    def setUp(self):
        super().setUp()
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3", return_value=False)
    def test_get_dual_cache_manager_prefer_redis(self, mock_feature_flag):
        """Test factory returns dual manager that prefers Redis when S3 flag is disabled."""

        manager = get_query_cache_manager(
            team=self.team,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, DualQueryCacheManager)
        self.assertEqual(manager.team_id, self.team.pk)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)
        self.assertFalse(manager.prefer_s3)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3", return_value=True)
    def test_get_dual_cache_manager_prefer_s3(self, mock_feature_flag):
        """Test factory returns dual manager that prefers S3 when S3 flag is enabled."""

        manager = get_query_cache_manager(
            team=self.team,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, DualQueryCacheManager)
        self.assertEqual(manager.team_id, self.team.pk)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)
        self.assertTrue(manager.prefer_s3)
