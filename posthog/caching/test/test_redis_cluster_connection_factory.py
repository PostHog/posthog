from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.caching.redis_cluster_connection_factory import warm_query_cache_connection


class TestWarmQueryCacheConnection(TestCase):
    @parameterized.expand(
        [
            ("test_mode", {"TEST": True, "STATIC_COLLECTION": False}),
            ("static_collection", {"TEST": False, "STATIC_COLLECTION": True}),
        ]
    )
    @patch("posthog.caching.redis_cluster_connection_factory.caches")
    def test_skips_in_excluded_modes(self, _name: str, settings_override: dict, mock_caches):
        with override_settings(CACHES={"query_cache": {"BACKEND": "fake"}}, **settings_override):
            warm_query_cache_connection()

        mock_caches.__getitem__.assert_not_called()

    @patch("posthog.caching.redis_cluster_connection_factory.caches")
    def test_skips_when_query_cache_not_configured(self, mock_caches):
        with override_settings(TEST=False, STATIC_COLLECTION=False, CACHES={"default": {"BACKEND": "fake"}}):
            warm_query_cache_connection()

        mock_caches.__getitem__.assert_not_called()

    @patch("posthog.caching.redis_cluster_connection_factory.caches")
    def test_triggers_query_cache_get_when_configured(self, mock_caches):
        mock_backend = MagicMock()
        mock_caches.__getitem__.return_value = mock_backend

        with override_settings(TEST=False, STATIC_COLLECTION=False, CACHES={"query_cache": {"BACKEND": "fake"}}):
            warm_query_cache_connection()

        mock_caches.__getitem__.assert_called_once_with("query_cache")
        mock_backend.get.assert_called_once_with("__startup_warmup__")

    @patch("posthog.caching.redis_cluster_connection_factory.logger")
    @patch("posthog.caching.redis_cluster_connection_factory.caches")
    def test_swallows_exceptions_and_logs(self, mock_caches, mock_logger):
        mock_backend = MagicMock()
        mock_backend.get.side_effect = ConnectionError("redis down")
        mock_caches.__getitem__.return_value = mock_backend

        with override_settings(TEST=False, STATIC_COLLECTION=False, CACHES={"query_cache": {"BACKEND": "fake"}}):
            warm_query_cache_connection()

        mock_logger.warning.assert_called_once()
        assert "query_cache_warmup_failure" in mock_logger.warning.call_args[0]
