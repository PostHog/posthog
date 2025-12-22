import json
import time
import hashlib
from collections.abc import Callable
from typing import Optional

from django.conf import settings
from django.core.cache import cache, caches

import structlog
from posthoganalytics import capture_exception
from prometheus_client import Counter, Histogram

from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)


DEFAULT_CACHE_MISS_TTL = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync
DEFAULT_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


def get_cache_writer_url(cache_alias: str) -> str:
    """
    Get writer Redis URL from cache alias.

    Django cache backends can have multiple URLs (writer + readers). This extracts
    the writer URL (first URL if multiple).

    Args:
        cache_alias: Django cache alias (e.g., 'flags_cache')

    Returns:
        Redis URL string for the writer
    """
    location = settings.CACHES[cache_alias]["LOCATION"]
    if isinstance(location, list):
        return location[0]
    elif isinstance(location, str):
        return location
    else:
        raise TypeError(f"Unsupported LOCATION type for cache alias '{cache_alias}': {type(location)}")


CACHE_SYNC_COUNTER = Counter(
    "posthog_hypercache_sync",
    "Number of times the hypercache cache sync task has been run",
    labelnames=["result", "namespace", "value"],
)

CACHE_SYNC_DURATION_HISTOGRAM = Histogram(
    "posthog_hypercache_sync_duration_seconds",
    "Time taken to sync hypercache in seconds",
    labelnames=["result", "namespace", "value"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
)

HYPERCACHE_CACHE_COUNTER = Counter(
    "posthog_hypercache_get_from_cache",
    "Metric tracking whether a hypercache was fetched from cache or not",
    labelnames=["result", "namespace", "value"],
)


_HYPER_CACHE_EMPTY_VALUE = "__missing__"


class HyperCacheStoreMissing:
    pass


# Custom key type for the hypercache
KeyType = Team | str | int


class HyperCache:
    """
    This is a helper cache for a standard model of multi-tier caching. It should be used for anything that is "client" facing - i.e. where SDKs will be calling in high volumes.
    The idea is simple - pre-cache every value we could possibly need. This might sound expensive but for read-heavy workloads it is a MUST.
    """

    def __init__(
        self,
        namespace: str,
        value: str,
        load_fn: Callable[[KeyType], dict | HyperCacheStoreMissing],
        token_based: bool = False,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        cache_miss_ttl: int = DEFAULT_CACHE_MISS_TTL,
        cache_alias: Optional[str] = None,
        batch_load_fn: Optional[Callable[[list[Team]], dict[int, dict]]] = None,
        enable_etag: bool = False,
        expiry_sorted_set_key: Optional[str] = None,
    ):
        self.namespace = namespace
        self.value = value
        self.load_fn = load_fn
        self.token_based = token_based
        self.cache_ttl = cache_ttl
        self.cache_miss_ttl = cache_miss_ttl
        self.batch_load_fn = batch_load_fn
        self.enable_etag = enable_etag
        self.expiry_sorted_set_key = expiry_sorted_set_key

        # Derive cache_client and redis_url from cache_alias (single source of truth)
        if cache_alias:
            self.cache_client = caches[cache_alias]
            self.redis_url = get_cache_writer_url(cache_alias)
        else:
            self.cache_client = cache
            self.redis_url = settings.REDIS_URL

    @staticmethod
    def team_from_key(key: KeyType) -> Team:
        if isinstance(key, Team):
            return key
        elif isinstance(key, str):
            return Team.objects.get(api_token=key)
        else:
            return Team.objects.get(id=key)

    def get_cache_identifier(self, team: Team) -> str | int:
        """
        Get the identifier used for cache keys and expiry tracking.

        For token-based caches, returns api_token. For ID-based caches, returns team.id.
        This ensures consistency between cache keys and expiry tracking entries.
        """
        return team.api_token if self.token_based else team.id

    def get_cache_key(self, key: KeyType) -> str:
        if self.token_based:
            if isinstance(key, Team):
                key = key.api_token
            return f"cache/team_tokens/{key}/{self.namespace}/{self.value}"
        else:
            if isinstance(key, Team):
                key = key.id
            return f"cache/teams/{key}/{self.namespace}/{self.value}"

    def get_etag_key(self, key: KeyType) -> str:
        return f"{self.get_cache_key(key)}:etag"

    def _compute_etag(self, json_data: str) -> str:
        return hashlib.sha256(json_data.encode("utf-8")).hexdigest()[:16]

    def get_from_cache(self, key: KeyType) -> dict | None:
        data, _ = self.get_from_cache_with_source(key)
        return data

    def get_from_cache_with_source(self, key: KeyType) -> tuple[dict | None, str]:
        cache_key = self.get_cache_key(key)
        data = self.cache_client.get(cache_key)

        if data:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()

            if data == _HYPER_CACHE_EMPTY_VALUE:
                return None, "redis"
            else:
                return json.loads(data), "redis"

        try:
            data = object_storage.read(cache_key, missing_ok=True)
            if data:
                response = json.loads(data)
                HYPERCACHE_CACHE_COUNTER.labels(result="hit_s3", namespace=self.namespace, value=self.value).inc()
                self._set_cache_value_redis(key, response)
                return response, "s3"
        except ObjectStorageError:
            pass

        # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
        data = self.load_fn(key)

        if isinstance(data, HyperCacheStoreMissing):
            self._set_cache_value_redis(key, None)
            HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
            return None, "db"

        self._set_cache_value_redis(key, data)
        HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
        return data, "db"

    def batch_get_from_cache(self, teams: list[Team]) -> dict[int, tuple[dict | None, str]]:
        """
        Batch get cached values for multiple teams using MGET.

        Only reads from Redis (no S3 or DB fallback). This is optimized for
        verification where we want to check what's in cache without side effects.

        Args:
            teams: List of Team objects to get cached values for

        Returns:
            Dict mapping team_id to (cached_data, source) tuples.
            source is "redis" for hits, "miss" for cache misses.
            Teams not in the result had no cache entry.
        """
        if not teams:
            return {}

        # Build cache keys for all teams
        cache_keys = [self.get_cache_key(team) for team in teams]

        # Batch get from Redis using get_many (Django cache's MGET wrapper)
        cached_values = self.cache_client.get_many(cache_keys)

        # Map results back to team IDs, counting hits and misses for batch metrics
        results: dict[int, tuple[dict | None, str]] = {}
        hit_count = 0
        miss_count = 0

        for team, cache_key in zip(teams, cache_keys):
            data = cached_values.get(cache_key)
            if data is not None:
                hit_count += 1
                if data == _HYPER_CACHE_EMPTY_VALUE:
                    results[team.id] = (None, "redis")
                else:
                    results[team.id] = (json.loads(data), "redis")
            else:
                # Cache miss - no S3/DB fallback in batch mode
                miss_count += 1
                results[team.id] = (None, "miss")

        # Batch increment Prometheus counters once per batch (avoids O(n) labels() overhead)
        if hit_count:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc(
                hit_count
            )
        if miss_count:
            HYPERCACHE_CACHE_COUNTER.labels(result="batch_miss", namespace=self.namespace, value=self.value).inc(
                miss_count
            )

        return results

    def get_etag(self, key: KeyType) -> str | None:
        """Get just the ETag for a cached value without loading the full response."""
        if not self.enable_etag:
            return None
        return self.cache_client.get(self.get_etag_key(key))

    def get_if_none_match(self, key: KeyType, client_etag: str | None) -> tuple[dict | None, str | None, bool]:
        """
        Check if client's ETag matches current cache, enabling HTTP 304 responses.

        Requires enable_etag=True in constructor. If ETags are disabled, always returns
        the full data with modified=True.

        Returns: (data, etag, modified)
        - If client_etag matches current: (None, current_etag, False) - 304 case
        - Otherwise: (data, current_etag, True) - 200 case with full data

        Note: If Redis fails during ETag check, gracefully degrades to returning
        the full data (treating as modified) rather than raising an exception.
        """
        if not self.enable_etag:
            data, _ = self.get_from_cache_with_source(key)
            return data, None, True

        try:
            current_etag = self.get_etag(key)

            if client_etag and current_etag and client_etag == current_etag:
                return None, current_etag, False

            data, source = self.get_from_cache_with_source(key)

            # If we loaded from S3 or DB, the ETag was set during _set_cache_value_redis
            # Re-fetch it to ensure we return the correct value
            if source in ("s3", "db"):
                current_etag = self.get_etag(key)

            return data, current_etag, True
        except Exception as e:
            # Gracefully degrade: return full data when Redis fails
            logger.warning(
                f"Redis failure during ETag check for {self.namespace}, falling back to full response", error=str(e)
            )
            try:
                data, _ = self.get_from_cache_with_source(key)
                return data, None, True
            except Exception:
                # If everything fails, return None with modified=True
                return None, None, True

    def update_cache(self, key: KeyType, ttl: Optional[int] = None) -> bool:
        logger.info(f"Syncing {self.namespace} cache for team {key}")

        start_time = time.time()
        success = False
        try:
            data = self.load_fn(key)
            self.set_cache_value(key, data, ttl=ttl)
            success = True
            return True
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync {self.namespace} cache for team {key}", exception=str(e))
            return False
        finally:
            duration = time.time() - start_time
            result = "success" if success else "failure"
            CACHE_SYNC_DURATION_HISTOGRAM.labels(result=result, namespace=self.namespace, value=self.value).observe(
                duration
            )
            CACHE_SYNC_COUNTER.labels(result=result, namespace=self.namespace, value=self.value).inc()

    def set_cache_value(
        self, key: KeyType, data: dict | None | HyperCacheStoreMissing, ttl: Optional[int] = None
    ) -> None:
        self._set_cache_value_redis(key, data, ttl=ttl)
        self._set_cache_value_s3(key, data, ttl=ttl)
        # Only track expiry when we have a Team object (avoids DB lookup)
        if isinstance(key, Team):
            self._track_expiry(key, data, ttl=ttl)

    def clear_cache(self, key: KeyType, kinds: Optional[list[str]] = None):
        """
        Only meant for use in tests
        """
        kinds = kinds or ["redis", "s3"]
        if "redis" in kinds:
            self.cache_client.delete(self.get_cache_key(key))
            # Always delete ETag key to clean up stale ETags from when enable_etag was True
            self.cache_client.delete(self.get_etag_key(key))
        if "s3" in kinds:
            object_storage.delete(self.get_cache_key(key))

    def _set_cache_value_redis(
        self, key: KeyType, data: dict | None | HyperCacheStoreMissing, ttl: Optional[int] = None
    ):
        cache_key = self.get_cache_key(key)
        etag_key = self.get_etag_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            self.cache_client.set(cache_key, _HYPER_CACHE_EMPTY_VALUE, timeout=self.cache_miss_ttl)
            # Always delete ETag key to clean up stale ETags from when enable_etag was True
            self.cache_client.delete(etag_key)
        else:
            timeout = ttl if ttl is not None else self.cache_ttl
            # Use sort_keys for deterministic serialization (consistent ETags)
            json_data = json.dumps(data, sort_keys=True)
            if self.enable_etag:
                etag = self._compute_etag(json_data)
                # Write data and ETag via pipeline (single Redis round trip)
                # Note this is not strictly atomic, but good enough for our use case
                self.cache_client.set_many({cache_key: json_data, etag_key: etag}, timeout=timeout)
            else:
                self.cache_client.set(cache_key, json_data, timeout=timeout)
                # Clean up stale ETag if ETags were previously enabled
                self.cache_client.delete(etag_key)

    def _set_cache_value_s3(self, key: KeyType, data: dict | None | HyperCacheStoreMissing, ttl: Optional[int] = None):
        """
        Write cache value to S3.

        Note: S3 uses fixed lifecycle policies regardless of Redis TTL.
        Custom TTLs only affect Redis expiration. If you need aligned S3/Redis TTLs,
        configure S3 bucket lifecycle rules to match your expected TTL range.
        """
        key = self.get_cache_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            object_storage.delete(key)
        else:
            # Use sort_keys for deterministic serialization (consistent ETags)
            object_storage.write(key, json.dumps(data, sort_keys=True))

    def _track_expiry(self, team: Team, data: dict | None | HyperCacheStoreMissing, ttl: Optional[int] = None) -> None:
        """
        Track cache expiration in Redis sorted set for efficient expiry queries.

        Only tracks if expiry_sorted_set_key is configured. Stores the cache identifier
        (token or team ID based on token_based setting) with expiry timestamp as score.
        """
        if not self.expiry_sorted_set_key:
            return

        # Don't track expiry for missing values
        if data is None or isinstance(data, HyperCacheStoreMissing):
            return

        try:
            identifier = self.get_cache_identifier(team)
            ttl_seconds = ttl if ttl is not None else self.cache_ttl
            expiry_timestamp = int(time.time()) + ttl_seconds

            redis_client = get_client(self.redis_url)
            redis_client.zadd(self.expiry_sorted_set_key, {str(identifier): expiry_timestamp})
        except Exception as e:
            # Don't fail cache writes if expiry tracking fails
            logger.warning(
                "Failed to track cache expiry",
                namespace=self.namespace,
                error=str(e),
                error_type=type(e).__name__,
            )
            capture_exception(e)
