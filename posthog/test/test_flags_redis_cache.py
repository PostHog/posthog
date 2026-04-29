"""
Tests for flags Redis cache dual-write functionality.

Tests the write_flags_to_cache() function which handles writing feature flags
to both shared and dedicated Redis caches when configured.
"""

import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS, write_flags_to_cache
from posthog.models import FeatureFlag
from posthog.models.feature_flag import set_feature_flags_for_team_in_cache


class TestFlagsRedisCache(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_writes_to_shared_cache_only_when_no_dedicated(self):
        """No dedicated cache configured - writes to shared cache only"""
        test_data = {"test": "data"}

        write_flags_to_cache("test-key", test_data, timeout=300)

        # Verify data was written to shared cache
        cached_value = cache.get("test-key")
        assert cached_value == test_data

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
            FLAGS_DEDICATED_CACHE_ALIAS: {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_dual_writes_when_dedicated_configured(self):
        """Dedicated cache configured - dual-writes to both shared and dedicated"""
        from django.core.cache import caches

        caches["default"].clear()
        caches[FLAGS_DEDICATED_CACHE_ALIAS].clear()

        test_data = {"test": "data"}

        write_flags_to_cache("test-key", test_data, timeout=300)

        # Verify data was written to both caches
        shared_value = caches["default"].get("test-key")
        dedicated_value = caches[FLAGS_DEDICATED_CACHE_ALIAS].get("test-key")

        assert shared_value == test_data
        assert dedicated_value == test_data

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
            FLAGS_DEDICATED_CACHE_ALIAS: {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_continues_on_dedicated_cache_failure(self):
        """Dedicated cache write failure - continues successfully, writes to shared"""
        from django.core.cache import caches

        test_data = {"test": "data"}

        # Create a mock for the dedicated cache that fails on set
        mock_dedicated_cache = MagicMock()
        mock_dedicated_cache.set.side_effect = Exception("Redis connection failed")

        shared_cache = caches["default"]
        shared_cache.clear()

        # Patch cache, caches, and settings to return our mocks
        with (
            patch("posthog.caching.flags_redis_cache.cache", shared_cache),
            patch("posthog.caching.flags_redis_cache.caches") as mock_caches,
            patch("posthog.caching.flags_redis_cache.settings") as mock_settings,
        ):

            def get_cache(name):
                if name == "default":
                    return shared_cache
                elif name == FLAGS_DEDICATED_CACHE_ALIAS:
                    return mock_dedicated_cache
                raise KeyError(f"Unknown cache: {name}")

            mock_caches.__getitem__.side_effect = get_cache
            mock_settings.CACHES = {"default": {}, FLAGS_DEDICATED_CACHE_ALIAS: {}}

            write_flags_to_cache("test-key", test_data, timeout=300)

            # Shared cache should still have the data
            shared_value = shared_cache.get("test-key")
            assert shared_value == test_data

            # Dedicated cache set should have been attempted
            mock_dedicated_cache.set.assert_called_once_with("test-key", test_data, 300)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
            FLAGS_DEDICATED_CACHE_ALIAS: {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_integration_with_set_feature_flags_for_team(self):
        """Integration test: set_feature_flags_for_team_in_cache uses write_flags_to_cache"""
        from django.core.cache import caches

        caches["default"].clear()
        caches[FLAGS_DEDICATED_CACHE_ALIAS].clear()

        # Create a feature flag
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        # Call the integration point
        set_feature_flags_for_team_in_cache(self.team.project_id)

        # Verify both caches received the data
        shared_data = caches["default"].get(f"team_feature_flags_{self.team.project_id}")
        dedicated_data = caches[FLAGS_DEDICATED_CACHE_ALIAS].get(f"team_feature_flags_{self.team.project_id}")

        assert shared_data is not None
        assert dedicated_data is not None

        # Verify the data is identical and correct
        assert shared_data == dedicated_data
        flags = json.loads(shared_data)
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"
        assert flags[0]["active"]
