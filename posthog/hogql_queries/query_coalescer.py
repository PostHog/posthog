import time
import uuid
import random
import threading
from collections.abc import Callable
from typing import NoReturn, Optional, TypeVar

import structlog
from prometheus_client import Counter, Histogram
from redis.exceptions import RedisError

from posthog import redis as posthog_redis

logger = structlog.get_logger(__name__)

LOCK_KEY_PREFIX = "query_coalesce"
ERROR_KEY_PREFIX = "query_coalesce_err"
LOCK_TTL_SECONDS = 60
ERROR_TTL_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.2
HEARTBEAT_INTERVAL_SECONDS = 20

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_EXTEND_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
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


class QueryCoalescingError(Exception):
    pass


class _Heartbeat:
    def __init__(self, redis, lock_key: str, lock_value: str):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(redis, lock_key, lock_value), daemon=True)
        self._thread.start()

    def _run(self, redis, lock_key: str, lock_value: str) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                redis.eval(_EXTEND_LOCK_SCRIPT, 1, lock_key, lock_value, LOCK_TTL_SECONDS)
            except RedisError:
                break

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


class QueryCoalescer:
    """Coalesces concurrent blocking queries with the same cache key.

    One request (leader) acquires a Redis lock and executes the query.
    A heartbeat thread keeps the lock alive while the leader runs.
    Concurrent requests (followers) poll the cache until the leader populates it.

    If the leader errors, the error is stored in Redis and followers raise.
    If the leader crashes (heartbeat stops), the lock expires and followers raise.

    In dry-run mode, followers emit metrics but execute independently (no waiting).
    """

    def __init__(self, cache_key: str, query_id: Optional[str] = None, *, dry_run: bool = False):
        self.cache_key = cache_key
        self.query_id = query_id or uuid.uuid4().hex
        self.dry_run = dry_run
        self._lock_value: str = ""
        self._is_leader: bool = False
        self._redis = posthog_redis.get_client()

    @property
    def _lock_key(self) -> str:
        return f"{LOCK_KEY_PREFIX}:{self.cache_key}"

    @property
    def _error_key(self) -> str:
        return f"{ERROR_KEY_PREFIX}:{self.cache_key}"

    def run_coalesced(
        self,
        execute: Callable[[], T],
        get_cache_data: Callable[[], Optional[dict]],
        build_response: Callable[[dict], T],
        is_fresh: Callable[[dict, float], bool],
        max_wait: float,
    ) -> T:
        """Execute with coalescing: one leader calculates, followers wait for cache.

        Args:
            execute: The function that calculates and caches the result (leader work).
            get_cache_data: Function to check cache for the result.
            build_response: Function to build a response from cached data (for followers).
            is_fresh: Predicate (data, leader_start) -> bool to determine if cached data
                is fresh enough. The caller owns freshness semantics.
            max_wait: Maximum time in seconds followers will wait for the leader's result.

        Returns the result from either execute() or from cache via build_response().
        Raises QueryCoalescingError if followers can't obtain a fresh result (leader
            error, leader heartbeat stops, or max_wait exceeded).
        """
        try:
            is_leader = self._try_acquire()
        except RedisError:
            return execute()

        if is_leader:
            heartbeat = _Heartbeat(self._redis, self._lock_key, self._lock_value)
            try:
                return execute()
            except Exception as e:
                self._store_error(e)
                raise
            finally:
                heartbeat.stop()
                try:
                    self._release()
                except RedisError:
                    pass

        cached_data = self._wait_for_result(get_cache_data, is_fresh, max_wait=max_wait)
        if cached_data is not None:
            return build_response(cached_data)
        if self.dry_run:
            return execute()
        self._raise_stored_error()

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

    def _store_error(self, error: Exception) -> None:
        try:
            self._redis.set(self._error_key, f"{type(error).__name__}: {error}", ex=ERROR_TTL_SECONDS)
        except RedisError:
            pass

    def _raise_stored_error(self) -> NoReturn:
        error_msg = None
        try:
            value = self._redis.get(self._error_key)
            if value is not None:
                error_msg = value.decode("utf-8") if isinstance(value, bytes) else value
        except RedisError:
            pass
        raise QueryCoalescingError(error_msg or "Leader failed or crashed without storing an error")

    def _wait_for_result(
        self,
        get_cache_data: Callable[[], Optional[dict]],
        is_fresh: Callable[[dict, float], bool],
        poll_interval: float = POLL_INTERVAL_SECONDS,
        max_wait: float = 300,
    ) -> Optional[dict]:
        if self.dry_run:
            return None

        lock_value = self._redis.get(self._lock_key)
        if lock_value is None:
            coalesce_counter.labels(outcome="follower_leader_gone").inc()
            return None
        leader_start = self._parse_lock_start_time(
            lock_value.decode("utf-8") if isinstance(lock_value, bytes) else lock_value
        )
        if leader_start is None:
            return None
        fresh_after = leader_start

        start = time.monotonic()

        while (time.monotonic() - start) < max_wait:
            data = get_cache_data()
            if data is not None and is_fresh(data, fresh_after):
                coalesce_wait_histogram.observe(time.monotonic() - start)
                coalesce_counter.labels(outcome="follower_hit").inc()
                return data

            lock_value = self._redis.get(self._lock_key)
            if lock_value is None:
                # Leader finished or died — check cache one last time to guard against a race
                # where the lock is release but cache is not written to yet
                data = get_cache_data()
                if data is not None and is_fresh(data, fresh_after):
                    coalesce_wait_histogram.observe(time.monotonic() - start)
                    coalesce_counter.labels(outcome="follower_hit").inc()
                    return data
                coalesce_counter.labels(outcome="follower_leader_gone").inc()
                return None

            time.sleep(poll_interval * (0.5 + random.random()))

        coalesce_counter.labels(outcome="follower_timeout").inc()
        return None

    @staticmethod
    def _parse_lock_start_time(lock_value: str) -> Optional[float]:
        try:
            return float(lock_value.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return None
