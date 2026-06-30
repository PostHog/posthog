import json
import time
import hashlib
from collections.abc import Callable
from typing import Optional

from django.conf import settings
from django.core.cache import cache, caches

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from posthoganalytics import capture_exception
from prometheus_client import Counter, Histogram

from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)


DEFAULT_CACHE_MISS_TTL = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync
DEFAULT_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


class HyperCacheDependencyUnavailable(Exception):
    """Raised by a ``load_fn`` when an upstream dependency is unavailable.

    HyperCache treats it as a transient signal, not a value: write paths skip the
    write so the existing entry is kept, and the read path returns a miss without
    caching a sentinel so the next read retries. Callers subclass it so the storage
    layer can catch this base without importing their exception types.
    """


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

HYPERCACHE_REBUILD_SKIPPED_COUNTER = Counter(
    "posthog_hypercache_rebuild_skipped",
    "Rebuilds skipped because a dependency was unavailable, keeping the existing entry",
    labelnames=["namespace", "reason"],
)

HYPERCACHE_WRITE_SKIPPED_UNCHANGED_COUNTER = Counter(
    "posthog_hypercache_write_skipped_unchanged",
    "Content-propagation writes skipped because the ETag was unchanged, avoiding a redundant rewrite",
    labelnames=["namespace", "value"],
)

CACHE_SYNC_DURATION_HISTOGRAM = Histogram(
    "posthog_hypercache_sync_duration_seconds",
    "Time taken to sync hypercache in seconds",
    labelnames=["result", "namespace", "value"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
)

CACHE_SYNC_SIZE_HISTOGRAM = Histogram(
    "posthog_hypercache_sync_size_bytes",
    "Size of hypercache entries in bytes",
    labelnames=["result", "namespace", "value"],
    buckets=(
        10_000,  # 10KB - small caches
        100_000,  # 100KB - medium caches
        256_000,  # 256KB - half of per-flag limit
        512_000,  # 512KB - per-flag limit (MAX_FEATURE_FLAG_FILTER_SIZE_BYTES)
        1_000_000,  # 1MB - approaching total limit
        1_500_000,  # 1.5MB
        3_000_000,  # 3MB - 2x limit (for overhead/outliers)
        5_000_000,  # 5MB - safety bucket
        float("inf"),
    ),
)

HYPERCACHE_CACHE_COUNTER = Counter(
    "posthog_hypercache_get_from_cache",
    "Metric tracking whether a hypercache was fetched from cache or not",
    labelnames=["result", "namespace", "value"],
)


_HYPER_CACHE_EMPTY_VALUE = "__missing__"


def emit_cache_sync_metrics(
    result: str,
    namespace: str,
    value: str,
    duration: float | None = None,
    size: int | None = None,
    increment_counter: bool = True,
) -> None:
    """
    Emit cache sync metrics for HyperCache operations.

    Args:
        result: "success" or "failure"
        namespace: Cache namespace (e.g., "feature_flags")
        value: Cache value identifier (e.g., "flags_with_cohorts.json")
        duration: Time taken in seconds; pass None to skip duration metric
        size: Cache entry size in bytes; pass None to skip size metric
        increment_counter: Whether to increment the sync counter (default True)

    Duration and size histograms are only observed when their respective values
    are provided. The counter is incremented unless increment_counter is False.
    """
    if duration is not None:
        CACHE_SYNC_DURATION_HISTOGRAM.labels(result=result, namespace=namespace, value=value).observe(duration)
    if size is not None:
        CACHE_SYNC_SIZE_HISTOGRAM.labels(result=result, namespace=namespace, value=value).observe(size)
    if increment_counter:
        CACHE_SYNC_COUNTER.labels(result=result, namespace=namespace, value=value).inc()


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
        hashed_credential_based: bool = False,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        cache_miss_ttl: int = DEFAULT_CACHE_MISS_TTL,
        cache_alias: Optional[str] = None,
        secondary_cache_alias: Optional[str] = None,
        batch_load_fn: Optional[Callable[[list[Team]], dict[int, dict]]] = None,
        enable_etag: bool = False,
        expiry_sorted_set_key: Optional[str] = None,
    ):
        if token_based and hashed_credential_based:
            raise ValueError("token_based and hashed_credential_based are mutually exclusive")

        self.namespace = namespace
        self.value = value
        self.load_fn = load_fn
        self.token_based = token_based
        # Credential-centric mode: keys by an already-hashed credential string
        # (sha256$<hex>) rather than a team. Used by the gateway credential
        # policy cache, where one blob exists per phx_/pha_ credential.
        self.hashed_credential_based = hashed_credential_based
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

        # Optional secondary cache; writes are mirrored on a best-effort basis.
        self.secondary_cache_client = (
            caches[secondary_cache_alias]
            if secondary_cache_alias and secondary_cache_alias in settings.CACHES
            else None
        )

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
        if self.hashed_credential_based:
            # key is the precomputed sha256$<hex> credential hash, never a Team.
            return f"cache/team_tokens_hashed/{key}/{self.namespace}/{self.value}"
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
        except (ObjectStorageError, BotoCoreError, ClientError, ValueError) as e:
            # Any storage-layer failure here (including a misconfigured S3 endpoint that
            # makes boto3 raise on client construction) must degrade to a cache miss and
            # fall through to load_fn, never bubble a 500 up to the request handler.
            # ValueError also catches json.JSONDecodeError from a corrupt blob, so capture
            # it — otherwise persistent corruption keeps missing silently as a plain hit_db.
            capture_exception(e)

        # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
        try:
            data = self.load_fn(key)
        except HyperCacheDependencyUnavailable:
            # Return a miss without caching a sentinel, so the next read retries. The
            # distinct "dependency_unavailable" source lets etag-aware callers fail
            # loud (retryable 503) instead of treating it like a plain cache miss; the
            # other callers (get_from_cache, verifiers) still see None and degrade.
            HYPERCACHE_CACHE_COUNTER.labels(
                result="dependency_unavailable", namespace=self.namespace, value=self.value
            ).inc()
            return None, "dependency_unavailable"

        if isinstance(data, HyperCacheStoreMissing):
            self._set_cache_value_redis(key, None)
            HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
            return None, "db"

        self._set_cache_value_redis(key, data)
        HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
        return data, "db"

    def batch_get_from_cache(self, teams: list[Team]) -> dict[int, tuple[dict | None, str, str | None]]:
        """
        Batch get cached values for multiple teams using MGET.

        Only reads from Redis (no S3 or DB fallback). This is optimized for
        verification where we want to check what's in cache without side effects.

        When ``enable_etag=True``, etag keys are fetched in the same MGET so
        the per-chunk Redis cost is one round trip regardless of how many
        callers in the verify loop need the etag. The returned etag is
        ``None`` when the key is absent (which the verifier surfaces as a
        ``MISSING_ETAG`` mismatch) or when ``enable_etag=False``.

        Args:
            teams: List of Team objects to get cached values for

        Returns:
            Dict mapping team_id to (cached_data, source, etag) tuples.
            source is "redis" for hits, "miss" for cache misses.
            etag is the cached etag string (or None when absent / disabled).
            Teams not in the result had no cache entry.
        """
        if not teams:
            return {}

        # Build cache keys for all teams. When etags are enabled, append the
        # etag keys to the same get_many call so we pay one round trip total.
        cache_keys = [self.get_cache_key(team) for team in teams]
        etag_keys = [self.get_etag_key(team) for team in teams] if self.enable_etag else []

        cached_values = self.cache_client.get_many(cache_keys + etag_keys)

        # Map results back to team IDs, counting hits and misses for batch metrics
        results: dict[int, tuple[dict | None, str, str | None]] = {}
        hit_count = 0
        miss_count = 0

        for i, (team, cache_key) in enumerate(zip(teams, cache_keys)):
            etag = cached_values.get(etag_keys[i]) if self.enable_etag else None
            data = cached_values.get(cache_key)
            if data is not None:
                hit_count += 1
                if data == _HYPER_CACHE_EMPTY_VALUE:
                    results[team.id] = (None, "redis", etag)
                else:
                    results[team.id] = (json.loads(data), "redis", etag)
            else:
                # Cache miss - no S3/DB fallback in batch mode
                miss_count += 1
                results[team.id] = (None, "miss", etag)

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
        the full data (treating as modified) rather than raising an exception. A
        dependency-unavailable signal on a cold miss is the exception: it is re-raised
        as HyperCacheDependencyUnavailable so the caller can fail loud and retryable.
        """
        if not self.enable_etag:
            data, source = self.get_from_cache_with_source(key)
            if source == "dependency_unavailable":
                raise HyperCacheDependencyUnavailable(f"Dependency unavailable loading {self.namespace}/{self.value}")
            return data, None, True

        try:
            current_etag = self.get_etag(key)

            if client_etag and current_etag and client_etag == current_etag:
                return None, current_etag, False

            data, source = self.get_from_cache_with_source(key)

            if source == "dependency_unavailable":
                raise HyperCacheDependencyUnavailable(f"Dependency unavailable loading {self.namespace}/{self.value}")

            # If we loaded from S3 or DB, the ETag was set during _set_cache_value_redis
            # Re-fetch it to ensure we return the correct value
            if source in ("s3", "db"):
                current_etag = self.get_etag(key)

            return data, current_etag, True
        except Exception as e:
            # A dependency-unavailable signal must reach the caller as a typed,
            # retryable error — not be swallowed like a Redis failure below.
            if isinstance(e, HyperCacheDependencyUnavailable):
                raise
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

    def update_cache(
        self,
        key: KeyType,
        ttl: Optional[int] = None,
        should_skip_write: Optional[Callable[[KeyType, dict], bool]] = None,
        data: dict | None = None,
    ) -> bool:
        """
        Load (or accept a pre-built) value, write it to all tiers, and emit sync metrics.

        Pass ``data`` to write an already-built value and skip ``load_fn``; when None the
        value is loaded via ``load_fn``.
        """
        logger.info(f"Syncing {self.namespace} cache for team {key}")

        start_time = time.time()
        success = False
        size: int | None = None
        try:
            value = self.load_fn(key) if data is None else data
            if should_skip_write is not None and isinstance(value, dict) and should_skip_write(key, value):
                # A caller-supplied predicate vetoed persisting this freshly loaded
                # value (e.g. it would overwrite good data with a degraded one). Keep
                # the existing entry; the predicate owns its own metric/logging.
                return False
            size = self.set_cache_value(key, value, ttl=ttl)
            success = True
            return True
        except HyperCacheDependencyUnavailable:
            # Skip the write to keep the existing entry, and count the skip so the skip
            # counter reflects the refresh/warm path too, not just the signal path. The
            # source of the failure already reported it, so don't report it again here.
            HYPERCACHE_REBUILD_SKIPPED_COUNTER.labels(namespace=self.namespace, reason="dependency_unavailable").inc()
            logger.warning(
                f"Skipping {self.namespace} cache sync for team {key}: dependency unavailable",
                namespace=self.namespace,
            )
            return False
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync {self.namespace} cache for team {key}", exception=str(e))
            return False
        finally:
            duration = time.time() - start_time
            result = "success" if success else "failure"
            emit_cache_sync_metrics(result, self.namespace, self.value, duration=duration, size=size)

    def set_cache_value(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: Optional[int] = None,
        skip_if_unchanged: bool = False,
    ) -> int | None:
        """
        Set cache value in Redis and S3, returning the serialized size in bytes.

        Returns None for None/missing values.

        When ``skip_if_unchanged`` is set, an ETag-enabled dict payload whose ETag matches
        the stored one is not rewritten (the counter records the skip; the serialized size
        is still returned). Skipping does not re-stamp expiry, so the cache must own an
        independent refresh path that does. ``expiry_sorted_set_key`` is the structural marker
        for that path (the refresh task reads the set to find expiring entries), so a refresh-less
        cache that opts into skipping raises rather than silently letting entries expire.
        """
        if skip_if_unchanged and not self.expiry_sorted_set_key:
            raise ValueError(
                "set_cache_value(skip_if_unchanged=True) requires expiry tracking "
                "(expiry_sorted_set_key) with a scheduled refresh that re-stamps the TTL"
            )
        json_data: str | None = None
        if skip_if_unchanged and self.enable_etag and isinstance(data, dict):
            json_data = json.dumps(data, sort_keys=True)
            if self._compute_etag(json_data) == self.get_etag(key):
                HYPERCACHE_WRITE_SKIPPED_UNCHANGED_COUNTER.labels(namespace=self.namespace, value=self.value).inc()
                return len(json_data)
        size = self._set_cache_value_redis(key, data, ttl=ttl, json_data=json_data)
        self._set_cache_value_s3(key, data, ttl=ttl)
        # Only track expiry when we have a Team object (avoids DB lookup)
        if isinstance(key, Team):
            self._track_expiry(key, data, ttl=ttl)
        return size

    def set_cache_value_redis_only(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: Optional[int] = None,
        track_expiry: bool = False,
    ) -> int | None:
        """
        Write only to the configured cache backend (self.cache_client), skipping S3.

        Use this for backfills and TTL refreshes where S3 already holds fresh data
        (e.g. via the normal sync() path) and the only cold tier is the cache backend.
        In prod with cache_alias=FLAGS_DEDICATED_CACHE_ALIAS this is the dedicated flags
        Redis; in dev/test it's whatever the alias resolves to.

        When track_expiry=True the expiry sorted-set entry is re-stamped too, keeping a
        redis-only refresh visible to the refresh task. Requires a Team key (the identifier
        derives from it without a DB lookup); raises ValueError otherwise rather than
        silently skipping the stamp.

        Returns the serialized size in bytes, or None for None/missing values.
        """
        if track_expiry and not isinstance(key, Team):
            raise ValueError("set_cache_value_redis_only(track_expiry=True) requires a Team key")
        size = self._set_cache_value_redis(key, data, ttl=ttl)
        if track_expiry and isinstance(key, Team):
            self._track_expiry(key, data, ttl=ttl)
        return size

    def clear_cache(self, key: KeyType, kinds: Optional[list[str]] = None):
        """Test helper alias for delete_cache_entry."""
        return self.delete_cache_entry(key, kinds)

    def delete_cache_entry(self, key: KeyType, kinds: Optional[list[str]] = None):
        """Hard-delete an entry from the given tiers (default redis + s3).

        Production-safe: the gateway credential projection uses this to revoke a
        credential's blob immediately — a missing key fails closed at the gateway.
        """
        kinds = kinds or ["redis", "s3"]
        try:
            if "redis" in kinds:
                self.cache_client.delete(self.get_cache_key(key))
                # Always delete ETag key to clean up stale ETags from when enable_etag was True
                self.cache_client.delete(self.get_etag_key(key))
            if "s3" in kinds:
                object_storage.delete(self.get_cache_key(key))
        finally:
            self._remove_expiry_tracking(key)

    def _mirror_to_secondary(self, op: Callable[..., None]) -> None:
        """Best-effort mirror write; failures are logged and captured, never propagated."""
        if self.secondary_cache_client is None:
            return
        try:
            op(self.secondary_cache_client)
        except Exception as e:
            logger.warning(
                "HyperCache secondary cache write failed",
                namespace=self.namespace,
                value=self.value,
                exc_info=True,
            )
            capture_exception(e)

    def _set_cache_value_redis(
        self,
        key: KeyType,
        data: dict | None | HyperCacheStoreMissing,
        ttl: Optional[int] = None,
        json_data: str | None = None,
    ) -> int | None:
        """
        Set cache value in Redis and return the serialized size in bytes.

        Returns None for None/missing values, otherwise returns len(json_data).

        Pass ``json_data`` to reuse an already-serialized payload (a caller that hashed it
        for an ETag comparison) instead of re-running ``json.dumps`` over a large value.
        """
        cache_key = self.get_cache_key(key)
        etag_key = self.get_etag_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            self.cache_client.set(cache_key, _HYPER_CACHE_EMPTY_VALUE, timeout=self.cache_miss_ttl)
            self._mirror_to_secondary(lambda c: c.set(cache_key, _HYPER_CACHE_EMPTY_VALUE, timeout=self.cache_miss_ttl))
            # Always delete ETag key to clean up stale ETags from when enable_etag was True
            self.cache_client.delete(etag_key)
            self._mirror_to_secondary(lambda c: c.delete(etag_key))
            return None
        else:
            timeout = ttl if ttl is not None else self.cache_ttl
            # Use sort_keys for deterministic serialization (consistent ETags)
            if json_data is None:
                json_data = json.dumps(data, sort_keys=True)
            if self.enable_etag:
                etag = self._compute_etag(json_data)
                # Write data and ETag via pipeline (single Redis round trip)
                # Note this is not strictly atomic, but good enough for our use case
                self.cache_client.set_many({cache_key: json_data, etag_key: etag}, timeout=timeout)
                self._mirror_to_secondary(lambda c: c.set_many({cache_key: json_data, etag_key: etag}, timeout=timeout))
            else:
                self.cache_client.set(cache_key, json_data, timeout=timeout)
                self._mirror_to_secondary(lambda c: c.set(cache_key, json_data, timeout=timeout))
                # Clean up stale ETag if ETags were previously enabled
                self.cache_client.delete(etag_key)
                self._mirror_to_secondary(lambda c: c.delete(etag_key))
            return len(json_data)

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

    def _remove_expiry_tracking(self, key: KeyType) -> None:
        """
        Remove cache expiration entry from Redis sorted set.

        Mirrors _track_expiry but for removal. Derives the identifier from the key
        type without requiring a DB lookup — mismatched types (int for token-based,
        str for ID-based) are silently skipped since the identifier can't be resolved.
        """
        if not self.expiry_sorted_set_key:
            return

        try:
            if isinstance(key, Team):
                identifier = str(self.get_cache_identifier(key))
            elif isinstance(key, int) and not self.token_based:
                identifier = str(key)
            elif isinstance(key, str) and self.token_based:
                identifier = key
            else:
                return

            redis_client = get_client(self.redis_url)
            redis_client.zrem(self.expiry_sorted_set_key, identifier)
        except Exception as e:
            logger.warning(
                "Failed to remove cache expiry tracking",
                namespace=self.namespace,
                error=str(e),
                error_type=type(e).__name__,
            )
            capture_exception(e)

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
