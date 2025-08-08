import json
import pytest
from unittest.mock import Mock
from django.core.cache import cache

from posthog.models.team import Team
from posthog.storage.hypercache import (
    HyperCache,
    HyperCacheStoreMissing,
    cache_key,
    _HYPER_CACHE_EMPTY_VALUE,
    DEFAULT_CACHE_TTL,
    DEFAULT_CACHE_MISS_TTL,
)
from posthog.storage.object_storage import ObjectStorageError
from posthog.storage import object_storage


class HyperCacheTestBase:
    """Base class for HyperCache tests with common test data and setup"""

    @property
    def mock_team(self) -> Mock:
        team = Mock(spec=Team)
        team.id = 123
        return team

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
        self.hypercache.clear_cache(self.mock_team)


class TestCacheKey(HyperCacheTestBase):
    def test_cache_key_format(self):
        """Test that cache key is formatted correctly"""
        key = cache_key(123, "test_namespace", "test_value")
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
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "redis"

    def test_get_from_cache_s3_fallback(self):
        """Test getting data from S3 when Redis cache misses"""
        # Clear Redis cache
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.delete(key)

        # Set up S3 with data
        object_storage.write(key, json.dumps(self.sample_data))

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "s3"

    def test_get_from_cache_s3_error_fallback_to_db(self):
        """Test getting data from database when both Redis and S3 fail"""
        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == {"default": "data"}
        assert source == "db"

    def test_get_from_cache_with_source_redis_hit(self):
        """Test getting data with source information - Redis hit"""
        # Set up cache with data
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "redis"

    def test_get_from_cache_with_source_s3_hit(self):
        """Test getting data with source information - S3 hit"""
        # Clear Redis cache
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.delete(key)

        # Set up S3 with data
        object_storage.write(key, json.dumps(self.sample_data))

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "s3"

    def test_get_from_cache_with_source_db_hit(self):
        """Test getting data with source information - Database hit"""
        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        result, source = self.hypercache.get_from_cache_with_source(self.mock_team)

        assert result == {"default": "data"}
        assert source == "db"

    def test_get_from_cache_with_source_empty(self):
        """Test getting data with source information - Empty result"""

        def load_fn_store_missing(team):
            return HyperCacheStoreMissing()

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn_store_missing)

        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        result, source = hc.get_from_cache_with_source(self.mock_team)

        assert result == _HYPER_CACHE_EMPTY_VALUE
        assert source == "empty"


class TestHyperCacheUpdateCache(HyperCacheTestBase):
    def test_update_cache_success(self):
        """Test successful cache update"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        result = hc.update_cache(self.mock_team)

        assert result is True

        # Verify data was cached
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
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

        result = hc.update_cache(self.mock_team)

        assert result is False


class TestHyperCacheClearCache(HyperCacheTestBase):
    def test_clear_cache_redis_only(self):
        """Test clearing only Redis cache"""
        # Set up both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)
        object_storage.write(key, json.dumps(self.sample_data))

        self.hypercache.clear_cache(self.mock_team, kinds=["redis"])

        # Redis should be cleared
        assert cache.get(key) is None
        # S3 should still exist
        assert object_storage.read(key) == json.dumps(self.sample_data)

    def test_clear_cache_s3_only(self):
        """Test clearing only S3 cache"""
        # Set up both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)
        object_storage.write(key, json.dumps(self.sample_data))

        self.hypercache.clear_cache(self.mock_team, kinds=["s3"])

        # Redis should still exist
        assert cache.get(key) == json.dumps(self.sample_data)
        # S3 should be cleared
        try:
            object_storage.read(key)
            assert False, "S3 data should have been deleted"
        except ObjectStorageError:
            pass  # Expected

    def test_clear_cache_both(self):
        """Test clearing both Redis and S3 cache"""
        # Set up both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)
        object_storage.write(key, json.dumps(self.sample_data))

        self.hypercache.clear_cache(self.mock_team, kinds=["redis", "s3"])

        # Both should be cleared
        assert cache.get(key) is None
        try:
            object_storage.read(key)
            assert False, "S3 data should have been deleted"
        except ObjectStorageError:
            pass  # Expected

    def test_clear_cache_default(self):
        """Test clearing cache with default kinds (both Redis and S3)"""
        # Set up both Redis and S3
        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cache.set(key, json.dumps(self.sample_data), timeout=DEFAULT_CACHE_TTL)
        object_storage.write(key, json.dumps(self.sample_data))

        self.hypercache.clear_cache(self.mock_team)

        # Both should be cleared
        assert cache.get(key) is None
        try:
            object_storage.read(key)
            assert False, "S3 data should have been deleted"
        except ObjectStorageError:
            pass  # Expected


class TestHyperCachePrivateMethods(HyperCacheTestBase):
    def test_set_cache_value_redis_with_data(self):
        """Test setting Redis cache with data"""
        self.hypercache._set_cache_value_redis(self.mock_team, self.sample_data)

        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cached_data = cache.get(key)
        assert cached_data == json.dumps(self.sample_data)

    def test_set_cache_value_redis_with_none(self):
        """Test setting Redis cache with None data"""
        self.hypercache._set_cache_value_redis(self.mock_team, None)

        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        cached_data = cache.get(key)
        assert cached_data == _HYPER_CACHE_EMPTY_VALUE

    def test_set_cache_value_s3(self):
        """Test setting S3 cache"""
        self.hypercache._set_cache_value_s3(self.mock_team, self.sample_data)

        key = cache_key(self.mock_team.id, self.hypercache.namespace, self.hypercache.value)
        s3_data = object_storage.read(key)
        assert s3_data == json.dumps(self.sample_data)


class TestHyperCacheIntegration(HyperCacheTestBase):
    def test_full_cache_flow(self):
        """Test the full cache flow: Redis miss -> S3 miss -> DB load -> cache set"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        # Get data (should load from DB and cache it)
        result, source = hc.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "db"

        # Verify Redis cache was set
        cached_data = cache.get(key)
        assert cached_data == json.dumps(self.sample_data)

        # Get data again (should hit Redis)
        result2, source2 = hc.get_from_cache_with_source(self.mock_team)

        assert result2 == self.sample_data
        assert source2 == "redis"

    def test_s3_fallback_and_cache_population(self):
        """Test S3 fallback and subsequent Redis cache population"""

        def load_fn(team):
            return self.sample_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear Redis but set S3
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
        cache.delete(key)
        object_storage.write(key, json.dumps(self.sample_data))

        # Get data (should hit S3 and populate Redis)
        result, source = hc.get_from_cache_with_source(self.mock_team)

        assert result == self.sample_data
        assert source == "s3"

        # Verify Redis cache was populated from S3
        cached_data = cache.get(key)
        assert cached_data == json.dumps(self.sample_data)


class TestHyperCacheEdgeCases(HyperCacheTestBase):
    def test_json_serialization_error(self):
        """Test handling of non-serializable data"""
        non_serializable_data = {"key": Mock()}  # Mock objects can't be JSON serialized

        def load_fn(team):
            return non_serializable_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        # This should raise a TypeError when trying to serialize
        with pytest.raises(TypeError):
            hc.get_from_cache(self.mock_team)

    def test_empty_namespace_and_value(self):
        """Test with empty namespace and value strings"""

        def load_fn(team):
            return {"data": "test"}

        hc = HyperCache(namespace="", value="", load_fn=load_fn)

        # Should still work with empty strings
        result, source = hc.get_from_cache_with_source(self.mock_team)
        assert result == {"data": "test"}
        assert source == "db"

    def test_very_large_data(self):
        """Test with very large data structures"""
        large_data = {"key": "x" * 1000000}  # 1MB string

        def load_fn(team):
            return large_data

        hc = HyperCache(namespace="test", value="value", load_fn=load_fn)

        # Clear both Redis and S3
        key = cache_key(self.mock_team.id, hc.namespace, hc.value)
        cache.delete(key)
        try:
            object_storage.delete(key)
        except ObjectStorageError:
            pass  # Key might not exist

        result, source = hc.get_from_cache_with_source(self.mock_team)

        assert result == large_data
        assert source == "db"
