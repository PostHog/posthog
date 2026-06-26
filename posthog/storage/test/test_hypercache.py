import json

import pytest
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import override_settings

from botocore.exceptions import BotoCoreError, ClientError
from parameterized import parameterized

from posthog.storage import object_storage
from posthog.storage.hypercache import (
    DEFAULT_CACHE_MISS_TTL,
    DEFAULT_CACHE_TTL,
    HyperCache,
    HyperCacheDependencyUnavailable,
    HyperCacheStoreMissing,
)


class HyperCacheTestBase:
    """Base class for HyperCache tests with common test data and setup"""

    team_id = 123

    @property
    def sample_data(self) -> dict:
        return {"key": "value", "nested": {"data": "test"}}

    @property
    def hypercache(self) -> HyperCache:
        def load_fn(team):
            return {"default": "data"}

        return HyperCache(namespace="test_namespace", value="test_value", load_fn=load_fn)

    def setUp(self):
        # Clear the cache for the commonly used hypercache
        self.team_id = 123
        self.hypercache.clear_cache(self.team_id)


class TestCacheKey(HyperCacheTestBase):
    def test_cache_key_format(self):
        """Test that cache key is formatted correctly"""
        key = self.hypercache.get_cache_key(123)
        assert key == "cache/teams/123/test_namespace/test_value"


class TestHyperCache(HyperCacheTestBase):
    def test_init(self):
        """Test HyperCache initialization"""

        def load_fn(team):
            return {"data": "test"}

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn, cache_ttl=3600, cache_miss_ttl=1800)

        assert hc.namespace == "test"
        assert hc.value == "value"
        assert hc.load_fn == load_fn
        assert hc.cache_ttl == 3600
        assert hc.cache_miss_ttl == 1800

    def test_init_default_ttl(self):
        """Test HyperCache initialization with default TTL values"""

        def load_fn(team):
            return {"data": "test"}

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        assert hc.cache_ttl == DEFAULT_CACHE_TTL
        assert hc.cache_miss_ttl == DEFAULT_CACHE_MISS_TTL


class TestHyperCacheGetFromCache(HyperCacheTestBase):
    def test_get_from_cache_redis_hit(self):
        """Test getting data from Redis cache"""
        # Set up cache with data
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        result, source = self.hypercache.get_from_cache_with_source(self.team_id)

        assert result == self.sample_data
        assert source == "redis"

    def test_get_from_cache_s3_fallback(self):
        """Test getting data from S3 when Redis cache misses"""
        # Clear Redis cache
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        self.hypercache.clear_cache(self.team_id, kinds=["redis"])

        result, source = self.hypercache.get_from_cache_with_source(self.team_id)

        assert result == self.sample_data
        assert source == "s3"

    def test_get_from_cache_s3_error_fallback_to_db(self):
        """Test getting data from database when both Redis and S3 fail"""
        # Clear both Redis and S3
        self.hypercache.clear_cache(self.team_id, kinds=["redis", "s3"])
        result, source = self.hypercache.get_from_cache_with_source(self.team_id)

        assert result == {"default": "data"}
        assert source == "db"

    @parameterized.expand(
        [
            ("value_error", ValueError("Invalid endpoint: https://${POSTHOG_DOMAIN}")),
            ("object_storage_error", object_storage.ObjectStorageError("read failed")),
            ("boto_core_error", BotoCoreError()),
            ("client_error", ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")),
        ]
    )
    def test_get_from_cache_s3_exception_falls_back_to_db(self, _name, exception):
        """A storage-layer failure on the S3 read must degrade to a cache miss, not a 500."""
        self.hypercache.clear_cache(self.team_id, kinds=["redis"])

        with patch.object(object_storage, "read", side_effect=exception):
            result, source = self.hypercache.get_from_cache_with_source(self.team_id)

        assert result == {"default": "data"}
        assert source == "db"

    def test_get_from_cache_corrupt_s3_payload_falls_back_to_db(self):
        """A malformed S3 blob (json.JSONDecodeError, a ValueError subclass) must degrade to a cache miss."""
        self.hypercache.clear_cache(self.team_id, kinds=["redis"])

        with patch.object(object_storage, "read", return_value="{not valid json"):
            result, source = self.hypercache.get_from_cache_with_source(self.team_id)

        assert result == {"default": "data"}
        assert source == "db"

    def test_get_from_cache_with_source_empty(self):
        """Test getting data with source information - Empty result"""

        def load_fn_store_missing(team):
            return HyperCacheStoreMissing()

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn_store_missing)

        # Clear both Redis and S3
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result is None
        assert source == "db"


class TestHyperCacheUpdateCache(HyperCacheTestBase):
    def test_update_cache_success(self):
        """Test successful cache update"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        result = hc.update_cache(self.team_id)

        assert result is True

        # Verify data was cached
        key = hc.get_cache_key(self.team_id)
        cached_data = cache.get(key)
        assert cached_data == json.dumps(self.sample_data)

        # Verify S3 was written
        s3_data = object_storage.read(key)
        assert s3_data == json.dumps(self.sample_data)

    def test_update_cache_failure(self):
        """Test cache update failure"""

        def load_fn_raises_exception(team):
            raise Exception("Database error")

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn_raises_exception)

        result = hc.update_cache(self.team_id)

        assert result is False


class TestHyperCacheDependencyUnavailable(HyperCacheTestBase):
    """A load_fn raising HyperCacheDependencyUnavailable skips the write and returns a
    miss without caching a sentinel."""

    @staticmethod
    def _load_fn_unavailable(team):
        raise HyperCacheDependencyUnavailable("persons db down")

    def test_update_cache_returns_false_and_writes_nothing(self):
        hc = HyperCache(namespace="dep_test", value="value", load_fn=self._load_fn_unavailable)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        with (
            patch("posthog.storage.hypercache.capture_exception") as mock_capture,
            patch("posthog.storage.hypercache.HYPERCACHE_REBUILD_SKIPPED_COUNTER") as mock_skipped,
        ):
            result = hc.update_cache(self.team_id)

        assert result is False
        # Nothing written, not even a miss sentinel, so a prior entry survives
        assert cache.get(hc.get_cache_key(self.team_id)) is None
        # The source of the failure already reported it, so update_cache does not
        mock_capture.assert_not_called()
        # The skip is counted so the refresh/warm path feeds the skip metric, not just
        # the signal path
        mock_skipped.labels.assert_called_once_with(namespace="dep_test", reason="dependency_unavailable")
        mock_skipped.labels.return_value.inc.assert_called_once()

    def test_get_from_cache_returns_transient_miss_without_sentinel(self):
        hc = HyperCache(namespace="dep_test", value="value", load_fn=self._load_fn_unavailable)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result is None
        # Distinct from a plain "db" miss so etag-aware callers can fail loud
        assert source == "dependency_unavailable"
        # No miss sentinel cached, so the next read retries instead of serving a cached miss
        assert cache.get(hc.get_cache_key(self.team_id)) is None

    def test_get_if_none_match_raises_when_etag_enabled_and_cold(self):
        # On a cold cache during an outage, the etag-aware read must surface the typed
        # signal to the caller (→ retryable 503), not degrade to a silent miss.
        hc = HyperCache(namespace="dep_test", value="value", load_fn=self._load_fn_unavailable, enable_etag=True)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        with pytest.raises(HyperCacheDependencyUnavailable):
            hc.get_if_none_match(self.team_id, client_etag=None)

    def test_get_if_none_match_raises_when_etag_disabled_and_cold(self):
        hc = HyperCache(namespace="dep_test", value="value", load_fn=self._load_fn_unavailable)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        with pytest.raises(HyperCacheDependencyUnavailable):
            hc.get_if_none_match(self.team_id, client_etag=None)

    def test_get_if_none_match_still_degrades_on_redis_failure(self):
        # A genuine Redis failure during the etag check must still degrade to full
        # data — only the dependency-unavailable signal is re-raised.
        hc = HyperCache(namespace="dep_test", value="value", load_fn=lambda team: {"ok": True}, enable_etag=True)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        with patch.object(hc, "get_etag", side_effect=Exception("redis down")):
            data, etag, modified = hc.get_if_none_match(self.team_id, client_etag=None)

        assert data == {"ok": True}
        assert etag is None
        assert modified is True


class TestHyperCacheIntegration(HyperCacheTestBase):
    def test_full_cache_flow(self):
        """Test the full cache flow: Redis miss -> S3 miss -> DB load -> cache set"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        # Get data (should load from DB and cache it)
        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result == self.sample_data
        assert source == "db"

        # Verify Redis cache was set
        cached_data, source = hc.get_from_cache_with_source(self.team_id)
        assert cached_data == self.sample_data
        assert source == "redis"

        # Get data again (should hit Redis)
        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result == self.sample_data
        assert source == "redis"

    def test_s3_fallback_and_cache_population(self):
        """Test S3 fallback and subsequent Redis cache population"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear Redis but set S3
        hc.set_cache_value(self.team_id, self.sample_data)
        hc.clear_cache(self.team_id, kinds=["redis"])

        # Get data (should hit S3 and populate Redis)
        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result == self.sample_data
        assert source == "s3"

        # Verify Redis cache was populated from S3
        cached_data, source = hc.get_from_cache_with_source(self.team_id)
        assert cached_data == self.sample_data
        assert source == "redis"


class TestHyperCacheEdgeCases(HyperCacheTestBase):
    def test_json_serialization_error(self):
        """Test handling of non-serializable data"""
        non_serializable_data = {"key": Mock()}  # Mock objects can't be JSON serialized

        def load_fn(team):
            return non_serializable_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        # This should raise a TypeError when trying to serialize
        with pytest.raises(TypeError):
            hc.get_from_cache(self.team_id)

    def test_empty_namespace_and_value(self):
        """Test with empty namespace and value strings"""

        def load_fn(team):
            return {"data": "test"}

        hc = HyperCache(namespace="", value="", load_fn=load_fn)

        # Should still work with empty strings
        result, source = hc.get_from_cache_with_source(self.team_id)
        assert result == {"data": "test"}
        assert source == "db"

    def test_very_large_data(self):
        """Test with very large data structures"""
        large_data = {"key": "x" * 1000000}  # 1MB string

        def load_fn(team):
            return large_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear both Redis and S3
        hc.clear_cache(self.team_id, kinds=["redis", "s3"])

        result, source = hc.get_from_cache_with_source(self.team_id)

        assert result == large_data
        assert source == "db"


class TestHyperCacheCustomCacheClient(BaseTest):
    """Test custom cache_client parameter for HyperCache"""

    @property
    def sample_data(self) -> dict:
        return {"key": "value", "nested": {"data": "test"}}

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-test-cache",
            },
        }
    )
    def test_custom_cache_client_isolation(self):
        """Test that custom cache_alias writes to dedicated cache, not default"""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        def load_fn(team):
            return self.sample_data

        # Create HyperCache with custom cache alias
        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
        )

        team_id = self.team.id

        # Write to cache
        hc.set_cache_value(team_id, self.sample_data)

        # Verify data is in dedicated cache
        cache_key = hc.get_cache_key(team_id)
        dedicated_value = caches["flags_dedicated"].get(cache_key)
        assert dedicated_value == json.dumps(self.sample_data)

        # Verify data is NOT in default cache
        default_value = caches["default"].get(cache_key)
        assert default_value is None

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-test-cache",
            },
        }
    )
    def test_custom_cache_client_reads_from_dedicated(self):
        """Test that reads use the custom cache alias"""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        def load_fn(team):
            return {"fallback": "data"}

        # Create HyperCache with custom cache alias
        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
        )

        team_id = self.team.id

        # Manually set data only in dedicated cache
        cache_key = hc.get_cache_key(team_id)
        caches["flags_dedicated"].set(cache_key, json.dumps(self.sample_data))

        # Get from cache should read from dedicated cache
        result, source = hc.get_from_cache_with_source(team_id)

        assert result == self.sample_data
        assert source == "redis"

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-test-cache",
            },
        }
    )
    def test_clear_cache_uses_custom_client(self):
        """Test that clear_cache targets the custom cache alias"""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        def load_fn(team):
            return self.sample_data

        # Create HyperCache with custom cache alias
        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
        )

        team_id = self.team.id

        # Write to both caches manually to test clearing
        cache_key = hc.get_cache_key(team_id)
        caches["flags_dedicated"].set(cache_key, json.dumps(self.sample_data))
        caches["default"].set(cache_key, json.dumps(self.sample_data))

        # Clear cache (redis only)
        hc.clear_cache(team_id, kinds=["redis"])

        # Verify dedicated cache was cleared
        dedicated_value = caches["flags_dedicated"].get(cache_key)
        assert dedicated_value is None

        # Verify default cache still has data (not touched)
        default_value = caches["default"].get(cache_key)
        assert default_value == json.dumps(self.sample_data)

    def test_default_cache_alias_backward_compatibility(self):
        """Test that HyperCache without cache_alias uses default cache"""

        def load_fn(team):
            return self.sample_data

        # Create HyperCache without cache_alias (should use default)
        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
        )

        team_id = self.team.id
        cache.clear()

        # Write to cache
        hc.set_cache_value(team_id, self.sample_data)

        # Verify data is in default cache
        cache_key = hc.get_cache_key(team_id)
        default_value = cache.get(cache_key)
        assert default_value == json.dumps(self.sample_data)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-test-cache",
            },
        }
    )
    def test_custom_cache_client_stores_etag_in_dedicated_cache(self):
        """Test that ETags are stored in the custom cache, not default"""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
            enable_etag=True,
        )

        team_id = self.team.id

        # Write to cache
        hc.set_cache_value(team_id, self.sample_data)

        # Verify ETag is in dedicated cache only
        etag_key = hc.get_etag_key(team_id)
        dedicated_etag = caches["flags_dedicated"].get(etag_key)
        default_etag = caches["default"].get(etag_key)

        assert dedicated_etag is not None
        assert len(dedicated_etag) == 16
        assert default_etag is None


class TestHyperCacheSecondaryCache(BaseTest):
    """Test the secondary_cache_alias dual-write path used during cluster migrations."""

    @property
    def sample_data(self) -> dict:
        return {"key": "value", "nested": {"data": "test"}}

    @parameterized.expand(
        [
            # (name, enable_etag, input_kind, key_kind)
            # input_kind: "sample" passes self.sample_data; "missing" passes HyperCacheStoreMissing()
            # key_kind: which key on the HyperCache to assert against ("cache_key" or "etag_key")
            ("data_payload", False, "sample", "cache_key"),
            ("etag_alongside_data", True, "sample", "etag_key"),
            ("missing_sentinel", False, "missing", "cache_key"),
        ]
    )
    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-secondary-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-secondary-test-cache",
            },
        }
    )
    def test_dual_writes_to_both_caches(self, _name, enable_etag, input_kind, key_kind):
        """Every write branch in _set_cache_value_redis is mirrored to the secondary cache."""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        data: dict | HyperCacheStoreMissing = self.sample_data if input_kind == "sample" else HyperCacheStoreMissing()

        def load_fn(team):
            return data

        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
            secondary_cache_alias="default",
            enable_etag=enable_etag,
        )

        team_id = self.team.id
        hc.set_cache_value(team_id, data)

        target_key = hc.get_etag_key(team_id) if key_kind == "etag_key" else hc.get_cache_key(team_id)
        primary_value = caches["flags_dedicated"].get(target_key)
        secondary_value = caches["default"].get(target_key)

        # Both caches must hold the same value. sort_keys=True ensures byte-for-byte
        # equality of the serialized payload, which also keeps ETags consistent.
        assert primary_value is not None
        assert primary_value == secondary_value

        # Branch-specific shape check on the dual-written value.
        if input_kind == "missing":
            assert primary_value == "__missing__"
        elif key_kind == "etag_key":
            # 16-char hex hash from HyperCache._compute_etag.
            assert isinstance(primary_value, str) and len(primary_value) == 16
        else:
            assert primary_value == json.dumps(self.sample_data, sort_keys=True)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "default-secondary-failure-test-cache",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "flags-dedicated-secondary-failure-test-cache",
            },
        }
    )
    def test_secondary_failure_does_not_block_primary(self):
        """A broken secondary cache must not raise — primary write stays authoritative."""
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            cache_alias="flags_dedicated",
            secondary_cache_alias="default",
        )

        team_id = self.team.id

        # Replace the secondary client with one that raises on every write op.
        broken = Mock()
        broken.set.side_effect = RuntimeError("secondary down")
        broken.set_many.side_effect = RuntimeError("secondary down")
        broken.delete.side_effect = RuntimeError("secondary down")
        hc.secondary_cache_client = broken

        # Must not raise.
        hc.set_cache_value(team_id, self.sample_data)

        # Primary cache still got the write.
        cache_key = hc.get_cache_key(team_id)
        primary_value = caches["flags_dedicated"].get(cache_key)
        assert primary_value == json.dumps(self.sample_data, sort_keys=True)

        # The broken secondary received the write attempt.
        broken.set.assert_called()

    def test_unknown_secondary_alias_falls_back_to_no_op(self):
        """A secondary_cache_alias not in settings.CACHES is silently ignored."""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=load_fn,
            secondary_cache_alias="does_not_exist",
        )

        assert hc.secondary_cache_client is None

        # set_cache_value should still work via the primary (default) cache.
        team_id = self.team.id
        cache.clear()
        hc.set_cache_value(team_id, self.sample_data)
        cache_key = hc.get_cache_key(team_id)
        assert cache.get(cache_key) == json.dumps(self.sample_data, sort_keys=True)


class TestHyperCacheBatchGetFromCache(BaseTest):
    """Tests for batch_get_from_cache() method using MGET optimization."""

    @property
    def sample_data(self) -> dict:
        return {"key": "value", "nested": {"data": "test"}}

    def create_hypercache(self) -> HyperCache:
        def load_fn(team):
            return {"default": "data"}

        return HyperCache(namespace="test_batch", value="test_value", load_fn=load_fn)

    def test_batch_get_from_cache_all_hits(self):
        """Test batch get when all teams have cached data."""
        hc = self.create_hypercache()
        teams = [self.team]

        # Populate cache
        hc.set_cache_value(self.team, self.sample_data)

        results = hc.batch_get_from_cache(teams)

        assert len(results) == 1
        assert self.team.id in results
        data, source, etag = results[self.team.id]
        assert source == "redis"
        assert data == self.sample_data
        # enable_etag defaults to False, so the third element is None
        assert etag is None

    def test_batch_get_from_cache_all_misses(self):
        """Test batch get when all teams have cache misses."""
        hc = self.create_hypercache()
        teams = [self.team]

        # Clear cache
        hc.clear_cache(self.team)

        results = hc.batch_get_from_cache(teams)

        assert len(results) == 1
        assert self.team.id in results
        data, source, etag = results[self.team.id]
        assert source == "miss"
        assert data is None
        assert etag is None

    def test_batch_get_from_cache_partial_hits(self):
        """Test batch get with mix of hits and misses."""
        from posthog.models.team import Team

        hc = self.create_hypercache()

        # Create a second team
        team2 = Team.objects.create(organization=self.organization, name="Test Team 2")
        teams = [self.team, team2]

        # Cache first team only
        hc.set_cache_value(self.team, self.sample_data)
        hc.clear_cache(team2)

        results = hc.batch_get_from_cache(teams)

        assert len(results) == 2

        # First team: hit
        data1, source1, _ = results[self.team.id]
        assert source1 == "redis"
        assert data1 == self.sample_data

        # Second team: miss
        data2, source2, _ = results[team2.id]
        assert source2 == "miss"
        assert data2 is None

    def test_batch_get_from_cache_empty_list(self):
        """Test batch get with empty team list."""
        hc = self.create_hypercache()

        results = hc.batch_get_from_cache([])

        assert results == {}

    def test_batch_get_from_cache_handles_empty_value_marker(self):
        """Test batch get correctly handles HyperCacheStoreMissing (None) cached values."""
        hc = self.create_hypercache()

        # Store a "missing" marker (None)
        hc.set_cache_value(self.team, HyperCacheStoreMissing())

        results = hc.batch_get_from_cache([self.team])

        # Should return (None, "redis", None) not (None, "miss", ...)
        # This is the cached "empty" marker, not a cache miss
        data, source, _ = results[self.team.id]
        assert data is None
        assert source == "redis"

    def test_batch_get_from_cache_uses_get_many(self):
        """Test that batch_get uses get_many (MGET) instead of individual gets."""
        hc = self.create_hypercache()
        teams = [self.team]

        # Populate cache first so there's data to return
        hc.set_cache_value(self.team, self.sample_data)

        # Track that get_many is called with the correct keys
        cache_key = hc.get_cache_key(self.team)
        get_many_called_keys = []

        original_get_many = hc.cache_client.get_many

        def track_get_many(keys):
            get_many_called_keys.extend(keys)
            return original_get_many(keys)

        with patch.object(hc.cache_client, "get_many", side_effect=track_get_many):
            results = hc.batch_get_from_cache(teams)

        # Verify get_many was called with the correct cache key
        assert cache_key in get_many_called_keys
        # Verify we got the expected result
        assert self.team.id in results
        data, source, _ = results[self.team.id]
        assert source == "redis"
        assert data == self.sample_data

    def test_batch_get_from_cache_no_s3_fallback(self):
        """Test that batch get does NOT fall back to S3 (verification-specific optimization)."""
        hc = self.create_hypercache()

        # Set data in S3 only, not Redis
        hc.set_cache_value(self.team, self.sample_data)
        hc.clear_cache(self.team, kinds=["redis"])

        results = hc.batch_get_from_cache([self.team])

        # Should return miss, NOT load from S3
        data, source, _ = results[self.team.id]
        assert source == "miss"
        assert data is None

    def test_batch_get_from_cache_returns_etag_when_enabled(self):
        """When enable_etag=True the etag rides on the same MGET as the payload,
        so callers (the verifier loop) get the etag without an extra Redis round
        trip per team. This is the property that prevents an N+1 GET inside
        verify_team_flags."""

        def load_fn(team):
            return {"default": "data"}

        hc = HyperCache(namespace="test_batch_etag", value="test_value", load_fn=load_fn, enable_etag=True)
        hc.set_cache_value(self.team, self.sample_data)

        results = hc.batch_get_from_cache([self.team])

        data, source, etag = results[self.team.id]
        assert source == "redis"
        assert data == self.sample_data
        # Real 16-char hex etag, not None
        assert etag is not None
        assert len(etag) == 16
        assert all(c in "0123456789abcdef" for c in etag)

    def test_batch_get_from_cache_etag_is_none_when_payload_present_without_etag(self):
        """The MISSING_ETAG verifier branch fires when payload exists but the etag
        key is absent. Confirm the batch surfaces that state as etag=None on a
        cache hit, so verify_team_flags can detect it without a per-team GET."""

        def load_fn(team):
            return {"default": "data"}

        hc = HyperCache(namespace="test_batch_no_etag", value="test_value", load_fn=load_fn, enable_etag=True)
        hc.set_cache_value(self.team, self.sample_data)
        # Simulate the regression class: payload present, etag absent.
        hc.cache_client.delete(hc.get_etag_key(self.team))

        results = hc.batch_get_from_cache([self.team])

        data, source, etag = results[self.team.id]
        assert source == "redis"
        assert data == self.sample_data
        assert etag is None

    def test_batch_get_from_cache_single_round_trip_with_etag(self):
        """Etag fetch piggybacks on the existing get_many call — exactly one Redis
        round trip per chunk regardless of whether enable_etag is True."""

        def load_fn(team):
            return {"default": "data"}

        hc = HyperCache(namespace="test_batch_one_call", value="test_value", load_fn=load_fn, enable_etag=True)
        hc.set_cache_value(self.team, self.sample_data)

        original_get_many = hc.cache_client.get_many
        get_many_call_count = 0
        captured_keys: list[list[str]] = []

        def counting_get_many(keys):
            nonlocal get_many_call_count
            get_many_call_count += 1
            captured_keys.append(list(keys))
            return original_get_many(keys)

        with patch.object(hc.cache_client, "get_many", side_effect=counting_get_many):
            hc.batch_get_from_cache([self.team])

        assert get_many_call_count == 1
        # The single MGET fetched both the payload key and the etag key.
        assert hc.get_cache_key(self.team) in captured_keys[0]
        assert hc.get_etag_key(self.team) in captured_keys[0]


class TestHyperCacheETagDisabled(HyperCacheTestBase):
    """Tests for HyperCache when ETag is disabled (default)"""

    def test_etag_not_stored_when_disabled(self):
        """Test that ETags are not stored when enable_etag=False"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        # ETag should not be stored
        etag = self.hypercache.get_etag(self.team_id)
        assert etag is None

        # Data should still be retrievable
        data = self.hypercache.get_from_cache(self.team_id)
        assert data == self.sample_data

    def test_get_if_none_match_returns_data_when_disabled(self):
        """Test that get_if_none_match always returns data when ETags disabled"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        # Even with a client ETag, should return full data
        data, etag, modified = self.hypercache.get_if_none_match(self.team_id, "some-etag")

        assert data == self.sample_data
        assert etag is None
        assert modified is True


class TestHyperCacheETag(HyperCacheTestBase):
    """Tests for ETag functionality in HyperCache"""

    @property
    def hypercache(self) -> HyperCache:
        """Override to enable ETag support for these tests"""

        def load_fn(team):
            return {"default": "data"}

        return HyperCache(namespace="test_namespace", value="test_value", load_fn=load_fn, enable_etag=True)

    def test_etag_key_format(self):
        """Test that ETag key is derived correctly from cache key"""
        etag_key = self.hypercache.get_etag_key(self.team_id)
        assert etag_key == "cache/teams/123/test_namespace/test_value:etag"

    def test_compute_etag_deterministic(self):
        """Test that ETag computation is deterministic for same input"""
        json_data = '{"key": "value"}'
        etag1 = self.hypercache._compute_etag(json_data)
        etag2 = self.hypercache._compute_etag(json_data)
        assert etag1 == etag2
        assert len(etag1) == 16  # SHA-256 truncated to 16 chars

    def test_compute_etag_different_for_different_data(self):
        """Test that different data produces different ETags"""
        etag1 = self.hypercache._compute_etag('{"key": "value1"}')
        etag2 = self.hypercache._compute_etag('{"key": "value2"}')
        assert etag1 != etag2

    def test_etag_consistent_for_same_dict_content(self):
        """Test that storing the same dict content produces consistent ETags.

        Uses different key orderings to verify sort_keys=True is working.
        This is important because data loaded from different sources (DB vs cache)
        might have different key orderings.
        """
        # Store data with keys in one order
        self.hypercache.set_cache_value(self.team_id, {"z": 3, "a": 1, "m": 2})
        etag1 = self.hypercache.get_etag(self.team_id)

        # Clear and store same data with keys in different order
        self.hypercache.clear_cache(self.team_id)
        self.hypercache.set_cache_value(self.team_id, {"a": 1, "m": 2, "z": 3})
        etag2 = self.hypercache.get_etag(self.team_id)

        # ETags should match because we use sort_keys=True
        assert etag1 == etag2

    def test_set_cache_value_stores_etag(self):
        """Test that set_cache_value stores an ETag alongside the data"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        etag = self.hypercache.get_etag(self.team_id)
        assert etag is not None
        assert len(etag) == 16

    def test_get_etag_returns_none_when_not_set(self):
        """Test that get_etag returns None when no ETag is stored"""
        self.hypercache.clear_cache(self.team_id)
        etag = self.hypercache.get_etag(self.team_id)
        assert etag is None

    def test_clear_cache_clears_etag(self):
        """Test that clear_cache also clears the ETag"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        assert self.hypercache.get_etag(self.team_id) is not None

        self.hypercache.clear_cache(self.team_id, kinds=["redis"])
        assert self.hypercache.get_etag(self.team_id) is None

    def test_get_if_none_match_returns_not_modified_when_etag_matches(self):
        """Test that get_if_none_match returns (None, etag, False) when ETags match"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        current_etag = self.hypercache.get_etag(self.team_id)

        data, etag, modified = self.hypercache.get_if_none_match(self.team_id, current_etag)

        assert data is None
        assert etag == current_etag
        assert modified is False

    def test_get_if_none_match_returns_data_when_etag_differs(self):
        """Test that get_if_none_match returns full data when ETags differ"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        data, etag, modified = self.hypercache.get_if_none_match(self.team_id, "wrong-etag")

        assert data == self.sample_data
        assert etag is not None
        assert modified is True

    def test_get_if_none_match_returns_data_when_no_client_etag(self):
        """Test that get_if_none_match returns full data when client sends no ETag"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        data, etag, modified = self.hypercache.get_if_none_match(self.team_id, None)

        assert data == self.sample_data
        assert etag is not None
        assert modified is True

    def test_etag_changes_when_data_changes(self):
        """Test that ETag changes when cached data is updated"""
        self.hypercache.set_cache_value(self.team_id, {"key": "value1"})
        etag1 = self.hypercache.get_etag(self.team_id)

        self.hypercache.set_cache_value(self.team_id, {"key": "value2"})
        etag2 = self.hypercache.get_etag(self.team_id)

        assert etag1 != etag2

    def test_etag_deleted_when_data_becomes_missing(self):
        """Test that ETags are deleted when data transitions to missing state"""
        # First, store data with ETag
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        old_etag = self.hypercache.get_etag(self.team_id)
        assert old_etag is not None

        # Store missing value
        self.hypercache.set_cache_value(self.team_id, HyperCacheStoreMissing())

        # ETag should be deleted
        assert self.hypercache.get_etag(self.team_id) is None

    def test_get_if_none_match_returns_modified_when_data_becomes_missing(self):
        """Test that old ETag returns modified=True when data transitions to missing"""
        # Store data and get ETag
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        old_etag = self.hypercache.get_etag(self.team_id)

        # Transition to missing
        self.hypercache.set_cache_value(self.team_id, HyperCacheStoreMissing())

        # Request with old ETag should return modified=True with null data
        data, etag, modified = self.hypercache.get_if_none_match(self.team_id, old_etag)
        assert modified is True
        assert data is None
        assert etag is None

    def test_etag_consistency_when_loaded_from_s3(self):
        """Test that ETag remains consistent when data is loaded from S3 fallback"""
        # Set data in both Redis and S3
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        original_etag = self.hypercache.get_etag(self.team_id)

        # Clear Redis only, leaving S3 intact
        self.hypercache.clear_cache(self.team_id, kinds=["redis"])

        # Load from S3 - should repopulate Redis with same ETag
        data, source = self.hypercache.get_from_cache_with_source(self.team_id)
        assert source == "s3"
        assert data == self.sample_data

        # ETag should be regenerated and match original
        new_etag = self.hypercache.get_etag(self.team_id)
        assert new_etag == original_etag

    def test_etag_consistency_when_loaded_from_db(self):
        """Test that ETag is generated correctly when loading from DB"""
        # Clear all caches
        self.hypercache.clear_cache(self.team_id, kinds=["redis", "s3"])

        # Load from DB
        data, source = self.hypercache.get_from_cache_with_source(self.team_id)
        assert source == "db"

        # ETag should be created and stored
        etag = self.hypercache.get_etag(self.team_id)
        assert etag is not None
        assert len(etag) == 16

        # Subsequent request with matching ETag should return not modified
        data2, etag2, modified = self.hypercache.get_if_none_match(self.team_id, etag)
        assert modified is False
        assert etag2 == etag

    def test_get_if_none_match_idempotent_304_responses(self):
        """Test that same ETag consistently returns not modified across multiple requests"""
        self.hypercache.set_cache_value(self.team_id, self.sample_data)
        etag = self.hypercache.get_etag(self.team_id)

        # Make 5 sequential requests with same ETag
        for i in range(5):
            data, returned_etag, modified = self.hypercache.get_if_none_match(self.team_id, etag)
            assert modified is False, f"Request {i + 1} should return not modified"
            assert returned_etag == etag
            assert data is None

    def test_get_if_none_match_handles_redis_failure_gracefully(self):
        """Test that get_if_none_match degrades gracefully when Redis fails during ETag check.

        When Redis is unavailable, the endpoint should NOT crash with a 500 error.
        Instead, it returns modified=True so the client knows to fetch fresh data.
        """
        # Set up data
        self.hypercache.set_cache_value(self.team_id, self.sample_data)

        # Mock Redis to fail on get operations
        def failing_get(key):
            raise ConnectionError("Redis unavailable")

        with patch.object(self.hypercache.cache_client, "get", side_effect=failing_get):
            # Should NOT raise - should gracefully degrade
            data, etag, modified = self.hypercache.get_if_none_match(self.team_id, "some-etag")

            # When Redis fails completely, we can't get data but we don't crash
            # The caller (API endpoint) should handle None data appropriately
            assert etag is None  # Can't get ETag when Redis fails
            assert modified is True  # Signal that client should treat as modified


class TestHyperCacheRemoveExpiryTracking(BaseTest):
    """Tests for expiry tracking removal via clear_cache."""

    SORTED_SET_KEY = "test_expiry_sorted_set"

    def _make_hypercache(self, token_based: bool = False) -> HyperCache:
        return HyperCache(
            namespace="test",
            value="value",
            load_fn=lambda key: {"data": "test"},
            token_based=token_based,
            expiry_sorted_set_key=self.SORTED_SET_KEY,
        )

    @parameterized.expand(
        [
            ("team_id_based", False, lambda self: self.team, lambda self: str(self.team.id)),
            ("team_token_based", True, lambda self: self.team, lambda self: str(self.team.api_token)),
            ("int_id_based", False, lambda self: 42, lambda self: "42"),
            ("str_token_based", True, lambda self: "phc_test_token", lambda self: "phc_test_token"),
        ]
    )
    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_removes_expiry_tracking(self, _name, token_based, key_fn, expected_id_fn, mock_get_client):
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        hc = self._make_hypercache(token_based=token_based)
        key = key_fn(self)
        expected_id = expected_id_fn(self)

        hc.clear_cache(key)

        mock_redis.zrem.assert_called_once_with(self.SORTED_SET_KEY, expected_id)

    @parameterized.expand(
        [
            ("int_token_based", True, 42),
            ("str_id_based", False, "some_string"),
        ]
    )
    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_skips_expiry_tracking_for_mismatched_types(self, _name, token_based, key, mock_get_client):
        hc = self._make_hypercache(token_based=token_based)

        hc.clear_cache(key)

        mock_get_client.assert_not_called()

    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_skips_expiry_tracking_when_no_sorted_set_key(self, mock_get_client):
        hc = HyperCache(
            namespace="test",
            value="value",
            load_fn=lambda key: {"data": "test"},
            expiry_sorted_set_key=None,
        )

        hc.clear_cache(42)

        mock_get_client.assert_not_called()

    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_logs_warning_on_redis_failure(self, mock_get_client):
        mock_redis = Mock()
        mock_redis.zrem.side_effect = ConnectionError("Redis unavailable")
        mock_get_client.return_value = mock_redis

        hc = self._make_hypercache(token_based=False)

        with patch("posthog.storage.hypercache.logger") as mock_logger:
            hc.clear_cache(42)

            args, kwargs = mock_logger.warning.call_args
            assert args[0] == "Failed to remove cache expiry tracking"
            assert kwargs["error_type"] == "ConnectionError"

    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_removes_expiry_tracking_regardless_of_kinds(self, mock_get_client):
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        hc = self._make_hypercache(token_based=False)
        hc.clear_cache(42, kinds=["redis"])

        mock_redis.zrem.assert_called_once_with(self.SORTED_SET_KEY, "42")

    @patch("posthog.storage.hypercache.get_client")
    def test_clear_cache_removes_expiry_tracking_despite_cache_deletion_failure(self, mock_get_client):
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        hc = self._make_hypercache(token_based=False)
        hc.cache_client = Mock()
        hc.cache_client.delete.side_effect = ConnectionError("Redis unavailable")

        with pytest.raises(ConnectionError):
            hc.clear_cache(42)

        mock_redis.zrem.assert_called_once_with(self.SORTED_SET_KEY, "42")


class TestHyperCacheSetCacheValueRedisOnly(BaseTest):
    """Tests for set_cache_value_redis_only, focused on the track_expiry option."""

    SORTED_SET_KEY = "test_redis_only_expiry_sorted_set"

    @property
    def sample_data(self) -> dict:
        return {"key": "value"}

    def _make_hypercache(self, secondary: bool = False) -> HyperCache:
        return HyperCache(
            namespace="test",
            value="value",
            load_fn=lambda key: {"data": "test"},
            token_based=True,
            expiry_sorted_set_key=self.SORTED_SET_KEY,
            cache_alias="flags_dedicated" if secondary else None,
            secondary_cache_alias="default" if secondary else None,
        )

    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.hypercache.get_client")
    def test_track_expiry_stamps_sorted_set_without_writing_s3(self, mock_get_client, mock_s3_write):
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        hc = self._make_hypercache()
        hc.set_cache_value_redis_only(self.team, self.sample_data, track_expiry=True)

        # Redis-only path never touches S3.
        mock_s3_write.assert_not_called()
        # Expiry tracking is stamped with the team's api_token (token-based cache).
        mock_redis.zadd.assert_called_once()
        sorted_set_key, member_map = mock_redis.zadd.call_args[0]
        assert sorted_set_key == self.SORTED_SET_KEY
        assert str(self.team.api_token) in member_map
        # The value is readable from the Redis tier afterwards.
        assert hc.get_from_cache(self.team.api_token) == self.sample_data

    @patch("posthog.storage.hypercache.get_client")
    def test_default_does_not_track_expiry(self, mock_get_client):
        hc = self._make_hypercache()
        hc.set_cache_value_redis_only(self.team, self.sample_data)

        # No expiry tracking by default → no Redis client for the sorted set is requested.
        mock_get_client.assert_not_called()

    @patch("posthog.storage.hypercache.get_client")
    def test_track_expiry_raises_for_non_team_key(self, mock_get_client):
        # track_expiry needs a Team to derive the identifier, so a non-Team key must fail
        # loud rather than silently skip the stamp.
        hc = self._make_hypercache()
        with pytest.raises(ValueError, match="requires a Team key"):
            hc.set_cache_value_redis_only(self.team.api_token, self.sample_data, track_expiry=True)

        mock_get_client.assert_not_called()

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "redis-only-secondary",
            },
            "flags_dedicated": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "redis-only-primary",
            },
        }
    )
    @patch("posthog.storage.hypercache.get_client")
    def test_track_expiry_mirrors_to_secondary_cache(self, mock_get_client):
        from django.core.cache import caches

        caches["default"].clear()
        caches["flags_dedicated"].clear()
        mock_get_client.return_value = Mock()

        hc = self._make_hypercache(secondary=True)
        hc.set_cache_value_redis_only(self.team, self.sample_data, track_expiry=True)

        cache_key = hc.get_cache_key(self.team)
        expected = json.dumps(self.sample_data, sort_keys=True)
        assert caches["flags_dedicated"].get(cache_key) == expected
        assert caches["default"].get(cache_key) == expected


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "skip-if-unchanged-test-cache",
        },
    }
)
class TestHyperCacheSkipIfUnchanged(BaseTest):
    """set_cache_value(skip_if_unchanged=True) avoids redundant rewrites of unchanged content."""

    @property
    def sample_data(self) -> dict:
        return {"key": "value", "nested": {"data": "test"}}

    def _hypercache(self, enable_etag: bool = True) -> HyperCache:
        return HyperCache(
            namespace="skip_ns",
            value="skip_value",
            load_fn=lambda team: {"default": "data"},
            enable_etag=enable_etag,
            expiry_sorted_set_key="skip_ns_expiry",
        )

    def test_requires_expiry_tracking(self):
        """skip_if_unchanged on a cache with no expiry tracking can't keep entries alive,
        so it raises rather than silently letting them expire."""
        hc = HyperCache(
            namespace="skip_ns",
            value="skip_value",
            load_fn=lambda team: {"default": "data"},
            enable_etag=True,
        )
        with pytest.raises(ValueError, match="expiry tracking"):
            hc.set_cache_value(self.team.id, self.sample_data, skip_if_unchanged=True)

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_skips_redundant_write_when_unchanged(self):
        """An ETag-enabled signal write of byte-identical data skips the Redis and S3 rewrites."""
        hc = self._hypercache()
        with patch.object(hc, "_set_cache_value_s3") as s3_write:
            hc.set_cache_value(self.team.id, self.sample_data, skip_if_unchanged=True)
            etag_before = hc.get_etag(self.team.id)

            with (
                patch.object(hc, "_set_cache_value_redis", wraps=hc._set_cache_value_redis) as redis_write,
                patch("posthog.storage.hypercache.HYPERCACHE_WRITE_SKIPPED_UNCHANGED_COUNTER") as skip_counter,
            ):
                size = hc.set_cache_value(self.team.id, self.sample_data, skip_if_unchanged=True)

        redis_write.assert_not_called()
        # The S3 PUT is the costlier write this optimization skips; only the first write reached it.
        s3_write.assert_called_once()
        # The skip counter is the only signal ops have that the optimization fired.
        skip_counter.labels.assert_called_once_with(namespace="skip_ns", value="skip_value")
        skip_counter.labels.return_value.inc.assert_called_once()
        assert size == len(json.dumps(self.sample_data, sort_keys=True))
        # The stored ETag is untouched, so readers comparing ETags won't refetch.
        assert hc.get_etag(self.team.id) == etag_before

    def test_changed_write_reuses_serialization_correctly(self):
        """When the content changed, the skip path's serialization is threaded into the Redis
        write instead of re-dumped; the stored value and ETag must still match the new payload."""
        hc = self._hypercache()
        changed = {"key": "changed", "extra": [3, 1, 2]}
        with patch.object(hc, "_set_cache_value_s3"):
            hc.set_cache_value(self.team.id, self.sample_data, skip_if_unchanged=True)
            hc.set_cache_value(self.team.id, changed, skip_if_unchanged=True)

        assert hc.get_from_cache(self.team.id) == changed
        assert hc.get_etag(self.team.id) == hc._compute_etag(json.dumps(changed, sort_keys=True))

    @parameterized.expand(
        [
            # Each case is a distinct way the skip guard fails to hold, so the write proceeds.
            ("content_changed", True, True, {"key": "changed"}),
            ("etag_disabled", False, True, None),
            ("skip_flag_off", True, False, None),
        ]
    )
    def test_write_proceeds(self, _name, enable_etag, skip_if_unchanged, second_data):
        """The write proceeds whenever the skip guard doesn't hold: content changed, ETags
        disabled, or skip_if_unchanged off (the refresh/backfill path, which rewrites
        unchanged content to extend the TTL)."""
        hc = self._hypercache(enable_etag=enable_etag)
        second = self.sample_data if second_data is None else second_data
        with patch.object(hc, "_set_cache_value_s3"):
            hc.set_cache_value(self.team.id, self.sample_data, skip_if_unchanged=skip_if_unchanged)
            with patch.object(hc, "_set_cache_value_redis", wraps=hc._set_cache_value_redis) as redis_write:
                hc.set_cache_value(self.team.id, second, skip_if_unchanged=skip_if_unchanged)
        redis_write.assert_called_once()
