import json

import pytest
from unittest.mock import Mock

from django.core.cache import cache

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
        self.hypercache.clear_cache(self.team_id, kinds=["redis", "s3"])

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
