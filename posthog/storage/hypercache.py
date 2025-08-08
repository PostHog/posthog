import json
from typing import Optional
from collections.abc import Callable
from django.core.cache import cache
from posthoganalytics import capture_exception
from prometheus_client import Counter
import structlog

from posthog.models.team import Team
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

HYPERCACHE_CACHE_COUNTER = Counter(
    "posthog_hypercache_get_from_cache",
    "Metric tracking whether a hypercache was fetched from cache or not",
    labelnames=["result", "namespace", "value"],
)


def cache_key(team_id: int, namespace: str, value: str) -> str:
    return f"cache/teams/{team_id}/{namespace}/{value}"


_HYPER_CACHE_EMPTY_VALUE = "__missing__"


class HyperCacheStoreMissingException(Exception):
    pass


class HyperCache:
    """
    This is a helper cache for a standard model of multi-tier caching. It should be used for anything that is "client" facing - i.e. where SDKs will be calling in high volumes.

    The idea is simple - pre-cache every value we could possibly need. This might sound expensive but for read-heavy workloads it is a MUST.
    """

    def __init__(
        self,
        namespace: str,
        value: str,
        load_fn: Callable[[Team], dict],
        cache_ttl: int = DEFAULT_CACHE_TTL,
        cache_miss_ttl: int = DEFAULT_CACHE_MISS_TTL,
    ):
        self.namespace = namespace
        self.value = value
        self.load_fn = load_fn
        self.cache_ttl = cache_ttl
        self.cache_miss_ttl = cache_miss_ttl

    def get_from_cache(self, team: Team) -> dict:
        data, _ = self.get_from_cache_with_source(team)
        return data

    def get_from_cache_with_source(self, team: Team) -> tuple[dict, str]:
        key = cache_key(team.id, self.namespace, self.value)
        data = cache.get(key)

        if data:
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()
            return json.loads(data), "redis"

        # Fallback to s3
        try:
            data = object_storage.read(key)
            if data:
                response = json.loads(data)
                HYPERCACHE_CACHE_COUNTER.labels(result="hit_s3", namespace=self.namespace, value=self.value).inc()
                self._set_cache_value_redis(team, response)
                return response, "s3"
        except ObjectStorageError:
            pass

        # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
        try:
            data = self.load_fn(team)
        except HyperCacheStoreMissingException:
            cache.set(key, _HYPER_CACHE_EMPTY_VALUE, timeout=DEFAULT_CACHE_TTL)
            HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
            return _HYPER_CACHE_EMPTY_VALUE, "empty"

        self._set_cache_value_redis(team, data)
        HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
        return data, "db"

    def update_cache(self, team: Team) -> bool:
        logger.info(f"Syncing {self.namespace} cache for team {team.id}")

        try:
            data = self.load_fn(team)
            self._set_cache_value_redis(team, data)
            if data is not None:
                self._set_cache_value_s3(team, data)

            return True
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to sync {self.namespace} cache for team {team.id}", exception=str(e))
            CACHE_SYNC_COUNTER.labels(result="failure", namespace=self.namespace, value=self.value).inc()
            return False

    def clear_cache(self, team: Team, kinds: Optional[list[str]] = None):
        """
        Only meant for use in tests
        """
        kinds = kinds or ["redis", "s3"]
        if "redis" in kinds:
            cache.delete(cache_key(team.id, self.namespace, self.value))
        if "s3" in kinds:
            object_storage.delete(cache_key(team.id, self.namespace, self.value))

    def _set_cache_value_redis(self, team: Team, data: dict | None):
        key = cache_key(team.id, self.namespace, self.value)
        if data is None:
            cache.set(key, _HYPER_CACHE_EMPTY_VALUE, timeout=DEFAULT_CACHE_MISS_TTL)
        else:
            cache.set(key, json.dumps(data), timeout=DEFAULT_CACHE_TTL)

    def _set_cache_value_s3(self, team: Team, data: dict):
        key = cache_key(team.id, self.namespace, self.value)
        object_storage.write(key, json.dumps(data))
