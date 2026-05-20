from posthog.test.base import BaseTest

from django.core.cache import cache
from django.test import override_settings

from posthog.caching.query_cache_routing import QUERY_CACHE_ALIAS, get_query_cache, use_cluster_cache


class TestQueryCacheRouting(BaseTest):
    def test_returns_default_cache_when_no_cluster_configured(self):
        result = get_query_cache()
        self.assertIs(result, cache)

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_returns_default_cache_when_alias_not_in_caches(self):
        self.assertFalse(use_cluster_cache())

    @override_settings(
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            QUERY_CACHE_ALIAS: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        }
    )
    def test_routes_to_cluster_cache_when_alias_configured(self):
        self.assertTrue(use_cluster_cache())
        self.assertIsNot(get_query_cache(), cache)
