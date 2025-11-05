import json
import time
from collections.abc import Callable
from typing import Optional

from django.core.cache import cache

import structlog
from posthoganalytics import capture_exception
from prometheus_client import Counter, Histogram

from posthog.models.team.team import Team
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)


DEFAULT_CACHE_MISS_TTL = 60 * 60 * 24  # 1 day - it will be invalidated by the daily sync
DEFAULT_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


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
    ):
        self.namespace = namespace
        self.value = value
        self.load_fn = load_fn
        self.token_based = token_based
        self.cache_ttl = cache_ttl
        self.cache_miss_ttl = cache_miss_ttl

    @staticmethod
    def team_from_key(key: KeyType) -> Team:
        if isinstance(key, Team):
            return key
        elif isinstance(key, str):
            return Team.objects.get(api_token=key)
        else:
            return Team.objects.get(id=key)

    def get_cache_key(self, key: KeyType) -> str:
        if self.token_based:
            if isinstance(key, Team):
                key = key.api_token
            return f"cache/team_tokens/{key}/{self.namespace}/{self.value}"
        else:
            if isinstance(key, Team):
                key = key.id
            return f"cache/teams/{key}/{self.namespace}/{self.value}"

    def get_from_cache(self, key: KeyType) -> dict | None:
        data, _ = self.get_from_cache_with_source(key)
        return data

    def get_from_cache_with_source(self, key: KeyType) -> tuple[dict | None, str]:
        cache_key = self.get_cache_key(key)
        data = cache.get(cache_key)

        if data:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()

            if data == _HYPER_CACHE_EMPTY_VALUE:
                return None, "redis"
            else:
                return json.loads(data), "redis"

        # Fallback to s3
        try:
            data = object_storage.read(cache_key)
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

    def update_cache(self, key: KeyType) -> bool:
        logger.info(f"Syncing {self.namespace} cache for team {key}")

        start_time = time.time()
        success = False
        try:
            data = self.load_fn(key)
            self.set_cache_value(key, data)
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

    def set_cache_value(self, key: KeyType, data: dict | None | HyperCacheStoreMissing) -> None:
        self._set_cache_value_redis(key, data)
        self._set_cache_value_s3(key, data)

    def clear_cache(self, key: KeyType, kinds: Optional[list[str]] = None):
        """
        Only meant for use in tests
        """
        kinds = kinds or ["redis", "s3"]
        if "redis" in kinds:
            cache.delete(self.get_cache_key(key))
        if "s3" in kinds:
            object_storage.delete(self.get_cache_key(key))

    def _set_cache_value_redis(self, key: KeyType, data: dict | None | HyperCacheStoreMissing):
        key = self.get_cache_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            cache.set(key, _HYPER_CACHE_EMPTY_VALUE, timeout=DEFAULT_CACHE_MISS_TTL)
        else:
            cache.set(key, json.dumps(data), timeout=DEFAULT_CACHE_TTL)

    def _set_cache_value_s3(self, key: KeyType, data: dict | None | HyperCacheStoreMissing):
        key = self.get_cache_key(key)
        if data is None or isinstance(data, HyperCacheStoreMissing):
            object_storage.delete(key)
        else:
            object_storage.write(key, json.dumps(data))
