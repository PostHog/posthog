from datetime import UTC, datetime, timedelta

import time_machine

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from posthog.caching.cache_version import bump_cache_version, read_cache_version

KEY = "test_cache_version"
TIMEOUT = 24 * 60 * 60


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestCacheVersion(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_bump_keeps_the_version_alive_past_the_first_timeout(self) -> None:
        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:
            read_cache_version(KEY, TIMEOUT)
            traveller.shift(timedelta(hours=23))
            bump_cache_version(KEY, TIMEOUT)
            traveller.shift(timedelta(hours=2))

            assert read_cache_version(KEY, TIMEOUT) == 1
