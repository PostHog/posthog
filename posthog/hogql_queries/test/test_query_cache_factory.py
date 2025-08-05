from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
from posthog.models import Team


class TestQueryCacheFactory(APIBaseTest):
    """Test query cache manager factory functionality."""

    def setUp(self):
        super().setUp()
        self.team_id = self.team.pk
        self.cache_key = "test_cache_key"
        self.insight_id = 123
        self.dashboard_id = 456

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_redis_cache_manager_default(self, mock_feature_flag):
        """Test factory returns Redis manager by default."""
        mock_feature_flag.return_value = False

        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, DjangoCacheQueryCacheManager)
        self.assertEqual(manager.team_id, self.team_id)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertEqual(manager.insight_id, self.insight_id)
        self.assertEqual(manager.dashboard_id, self.dashboard_id)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_redis_cache_manager_feature_flag_off(self, mock_feature_flag):
        """Test factory returns Redis manager when feature flag is off."""
        mock_feature_flag.return_value = False

        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
        )

        self.assertIsInstance(manager, DjangoCacheQueryCacheManager)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_s3_cache_manager(self, mock_feature_flag):
        """Test factory returns S3 manager when feature flag is enabled."""
        mock_feature_flag.return_value = True

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

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_cache_manager_with_optional_params(self, mock_feature_flag):
        """Test factory with optional parameters."""
        mock_feature_flag.return_value = False

        # Test without insight_id and dashboard_id
        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
        )

        self.assertIsInstance(manager, DjangoCacheQueryCacheManager)
        self.assertEqual(manager.team_id, self.team_id)
        self.assertEqual(manager.cache_key, self.cache_key)
        self.assertIsNone(manager.insight_id)
        self.assertIsNone(manager.dashboard_id)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_s3_cache_manager_with_user(self, mock_feature_flag):
        """Test factory returns S3 manager when feature flag is enabled for user."""
        mock_feature_flag.return_value = True

        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
            user=self.user,
        )

        self.assertIsInstance(manager, S3QueryCacheManager)
        mock_feature_flag.assert_called_once_with(self.team, user=self.user)

    @patch("posthog.hogql_queries.query_cache_factory.query_cache_use_s3")
    def test_get_redis_cache_manager_with_user(self, mock_feature_flag):
        """Test factory returns Redis manager when feature flag is disabled for user."""
        mock_feature_flag.return_value = False

        manager = get_query_cache_manager(
            team_id=self.team_id,
            cache_key=self.cache_key,
            insight_id=self.insight_id,
            dashboard_id=self.dashboard_id,
            user=self.user,
        )

        self.assertIsInstance(manager, DjangoCacheQueryCacheManager)
        mock_feature_flag.assert_called_once_with(self.team, user=self.user)

    @patch("posthog.models.Team.objects.get")
    def test_get_cache_manager_team_not_found_fallback_to_settings(self, mock_team_get):
        """Test factory falls back to settings when team doesn't exist."""
        mock_team_get.side_effect = Team.DoesNotExist()

        with self.settings(QUERY_CACHE_BACKEND="s3"):
            manager = get_query_cache_manager(
                team_id=99999,  # Non-existent team
                cache_key=self.cache_key,
            )

            self.assertIsInstance(manager, S3QueryCacheManager)

    @patch("posthog.models.Team.objects.get")
    def test_get_cache_manager_team_not_found_fallback_to_redis(self, mock_team_get):
        """Test factory falls back to Redis when team doesn't exist and no S3 setting."""
        mock_team_get.side_effect = Team.DoesNotExist()

        with self.settings(QUERY_CACHE_BACKEND="redis"):
            manager = get_query_cache_manager(
                team_id=99999,  # Non-existent team
                cache_key=self.cache_key,
            )

            self.assertIsInstance(manager, DjangoCacheQueryCacheManager)
