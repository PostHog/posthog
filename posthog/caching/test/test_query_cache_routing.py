from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from posthog.caching.query_cache_routing import QUERY_CACHE_ALIAS, get_query_cache, use_cluster_cache


class TestQueryCacheRouting(BaseTest):
    def test_returns_default_cache_when_no_cluster_configured(self):
        result = get_query_cache(self.team.pk)
        self.assertIs(result, cache)

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_returns_default_cache_when_alias_not_in_caches(self):
        self.assertFalse(use_cluster_cache(self.team.pk))

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            QUERY_CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
    )
    @patch("posthog.caching.query_cache_routing.posthoganalytics.feature_enabled", return_value=True)
    def test_returns_cluster_cache_when_flag_enabled(self, _mock_flag):
        result = get_query_cache(self.team.pk)
        self.assertIsNot(result, cache)

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            QUERY_CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
    )
    @patch("posthog.caching.query_cache_routing.posthoganalytics.feature_enabled", return_value=False)
    def test_returns_default_cache_when_flag_disabled(self, _mock_flag):
        result = get_query_cache(self.team.pk)
        self.assertIs(result, cache)

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            QUERY_CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
    )
    @patch("posthog.caching.query_cache_routing.posthoganalytics.feature_enabled", side_effect=[True, False])
    def test_routes_back_to_default_cache_when_flag_flips_off(self, mock_flag):
        cluster_cache = get_query_cache(self.team.pk)
        default_cache = get_query_cache(self.team.pk)

        self.assertIsNot(cluster_cache, cache)
        self.assertIs(default_cache, cache)
        self.assertEqual(mock_flag.call_count, 2)
