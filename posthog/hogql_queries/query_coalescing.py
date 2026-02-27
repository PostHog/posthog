import time
import uuid
from collections.abc import Callable
from typing import Optional, TypeVar

import structlog
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog import redis as posthog_redis

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "query_coalesce"
LOCK_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.2
MAX_LEADER_AGE_SECONDS = 30

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

coalesce_counter = Counter(
    "query_coalesce_total",
    "Query coalescing outcomes",
    labelnames=["outcome"],
)

coalesce_wait_histogram = Histogram(
    "query_coalesce_wait_seconds",
    "Time followers spent waiting for leader result",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

T = TypeVar("T")


class QueryCoalescer:
    """Coalesces concurrent blocking queries with the same cache key.

    One request (leader) acquires a Redis lock and executes the query.
    Concurrent requests (followers) poll the cache until the leader populates it.

    In dry-run mode, followers emit metrics but execute independently (no waiting).
    """

    def __init__(self, cache_key: str, query_id: Optional[str] = None, *, dry_run: bool = False):
        self.cache_key = cache_key
        self.query_id = query_id or uuid.uuid4().hex
        self.dry_run = dry_run
        self._lock_value: str = ""
        self._is_leader: bool = False
        self._created_at: float = time.time()
        self._redis = posthog_redis.get_client()

    @property
    def _lock_key(self) -> str:
        return f"{LOCK_KEY_PREFIX}:{self.cache_key}"

    def run_coalesced(
        self,
        execute: Callable[[], T],
        get_cache_data: Callable[[], Optional[dict]],
        build_response: Callable[[dict], T],
    ) -> T:
        """Execute with coalescing: one leader calculates, followers wait for cache.

        Args:
            execute: The function that calculates and caches the result (leader work).
            get_cache_data: Function to check cache for the result.
            build_response: Function to build a response from cached data (for followers).

        Returns the result from either execute() or from cache via build_response().
        """
        try:
            is_leader = self._try_acquire()
        except RedisError:
            return execute()

        if is_leader:
            try:
                return execute()
            finally:
                try:
                    self._release()
                except RedisError:
                    pass
        else:
            cached_data = self._wait_for_result(get_cache_data)
            if cached_data is not None:
                return build_response(cached_data)
            return execute()

    def _try_acquire(self) -> bool:
        self._lock_value = f"{self.query_id}:{time.time()}"
        acquired = self._redis.set(self._lock_key, self._lock_value, nx=True, ex=LOCK_TTL_SECONDS)
        self._is_leader = bool(acquired)
        if self._is_leader:
            coalesce_counter.labels(outcome="leader").inc()
        elif self.dry_run:
            coalesce_counter.labels(outcome="follower_dry_run").inc()
        return self._is_leader

    def _release(self) -> None:
        if self._is_leader and self._lock_value:
            self._redis.eval(_RELEASE_LOCK_SCRIPT, 1, self._lock_key, self._lock_value)

    def _wait_for_result(
        self,
        get_cache_data: Callable[[], Optional[dict]],
        poll_interval: float = POLL_INTERVAL_SECONDS,
        max_leader_age: float = MAX_LEADER_AGE_SECONDS,
    ) -> Optional[dict]:
        if self.dry_run:
            return None

        start = time.monotonic()

        while (time.monotonic() - start) < max_leader_age:
            data = get_cache_data()
            if data is not None and self._is_fresh(data):
                coalesce_wait_histogram.observe(time.monotonic() - start)
                coalesce_counter.labels(outcome="follower_hit").inc()
                return data

            lock_value = self._redis.get(self._lock_key)
            if lock_value is None:
                coalesce_counter.labels(outcome="follower_leader_gone").inc()
                return None

            leader_start = self._parse_lock_start_time(
                lock_value.decode("utf-8") if isinstance(lock_value, bytes) else lock_value
            )
            if leader_start and (time.time() - leader_start) > max_leader_age:
                coalesce_counter.labels(outcome="follower_timeout").inc()
                return None

            time.sleep(poll_interval)

        coalesce_counter.labels(outcome="follower_timeout").inc()
        return None

    def _is_fresh(self, data: dict) -> bool:
        last_refresh = data.get("last_refresh")
        if last_refresh is None:
            return False
        if isinstance(last_refresh, str):
            from datetime import datetime

            last_refresh = datetime.fromisoformat(last_refresh)
        return last_refresh.timestamp() >= self._created_at

    @staticmethod
    def _parse_lock_start_time(lock_value: str) -> Optional[float]:
        try:
            return float(lock_value.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return None
