import json

import pytest
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import override_settings

from posthog.storage import object_storage
from posthog.storage.hypercache import DEFAULT_CACHE_MISS_TTL, DEFAULT_CACHE_TTL, HyperCache, HyperCacheStoreMissing


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
        data, source = results[self.team.id]
        assert source == "redis"
        assert data == self.sample_data

    def test_batch_get_from_cache_all_misses(self):
        """Test batch get when all teams have cache misses."""
        hc = self.create_hypercache()
        teams = [self.team]

        # Clear cache
        hc.clear_cache(self.team)

        results = hc.batch_get_from_cache(teams)

        assert len(results) == 1
        assert self.team.id in results
        data, source = results[self.team.id]
        assert source == "miss"
        assert data is None

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
        data1, source1 = results[self.team.id]
        assert source1 == "redis"
        assert data1 == self.sample_data

        # Second team: miss
        data2, source2 = results[team2.id]
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

        # Should return (None, "redis") not (None, "miss")
        # This is the cached "empty" marker, not a cache miss
        data, source = results[self.team.id]
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
        data, source = results[self.team.id]
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
        data, source = results[self.team.id]
        assert source == "miss"
        assert data is None


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
            assert modified is False, f"Request {i+1} should return not modified"
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
