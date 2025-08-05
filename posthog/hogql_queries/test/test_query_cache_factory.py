from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_cache import RedisQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager


class TestQueryCacheFactory(APIBaseTest):
    """Test query cache manager factory functionality."""

    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456

    def test_get_redis_cache_manager_default(self):
        """Test factory returns Redis manager by default."""
        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, RedisQueryCacheManager)
        self.assertEqual(manager.team_id, self.team_id)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)

    def test_get_redis_cache_manager_explicit(self):
        """Test factory returns Redis manager when explicitly configured."""
        with self.settings(QUERY_CACHE_BACKEND="redis"):
            manager = get_query_cache_manager(
                team_id=self.team_id,
                cache_key=self.cache_key,
                insight_id=self.insight_id,
                dashboard_id=self.dashboard_id,
            )

            self.assertIsInstance(manager, RedisQueryCacheManager)

    def test_get_s3_cache_manager(self):
        """Test factory returns S3 manager when configured."""
        with self.settings(QUERY_CACHE_BACKEND="s3"):
            manager = get_query_cache_manager(
                team_id=self.team_id,
                cache_key=self.cache_key,
                insight_id=self.insight_id,
                dashboard_id=self.dashboard_id,
            )

            self.assertIsInstance(manager, S3QueryCacheManager)
            self.assertEqual(manager.team_id, self.team_id)
            self.assertEqual(manager.cache_key, self.cache_key)
            self.assertEqual(manager.insight_id, self.insight_id)
            self.assertEqual(manager.dashboard_id, self.dashboard_id)

    def test_get_cache_manager_with_optional_params(self):
        """Test factory with optional parameters."""
        # Test without insight_id and dashboard_id
        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
        )

        self.assertIsInstance(manager, RedisQueryCacheManager)
        self.assertEqual(manager.team_id, self.team_id)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertIsNone(manager.insight_id)
        self.assertIsNone(manager.dashboard_id)

    def test_get_cache_manager_unknown_backend(self):
        """Test factory falls back to Redis for unknown backends."""
        with self.settings(QUERY_CACHE_BACKEND="unknown"):
            manager = get_query_cache_manager(
                team_id=self.team_id,
                cache_key=self.cache_key,
            )

            self.assertIsInstance(manager, RedisQueryCacheManager)
