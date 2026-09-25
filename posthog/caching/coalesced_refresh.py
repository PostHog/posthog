"""Experimental Redis-backed stale-while-revalidate cache refresh."""

import uuid
from collections.abc import Callable
from typing import Generic, TypeVar, cast

from django.core.cache import caches

import structlog
from django_redis import get_redis_connection
from django_redis.cache import RedisCache
from django_redis.exceptions import ConnectionInterrupted
from opentelemetry import trace
from redis.exceptions import LockNotOwnedError, RedisError
from redis.lock import Lock

logger = structlog.get_logger(__name__)
T = TypeVar("T")

_PUBLISH_IF_OWNER = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('psetex', KEYS[2], ARGV[3], ARGV[2])
return 1
"""


class CacheRefreshInProgress(Exception):
    pass


class CoalescedCacheRefresh(Generic[T]):
    """Experimental shared refresh coordination; requires the default Redis cache."""

    def __init__(
        self,
        key: str,
        *,
        timeout: int,
        is_stale: Callable[[T | None], bool],
        is_valid: Callable[[object], bool],
        refresh: Callable[[Callable[[], bool]], T],
        lease_seconds: int = 60,
        cold_wait_seconds: float = 2,
        failure_backoff_seconds: int = 30,
    ) -> None:
        self.key = key
        self.timeout = timeout
        self.is_stale = is_stale
        self.is_valid = is_valid
        self.refresh = refresh
        self.lease_seconds = lease_seconds
        self.cold_wait_seconds = cold_wait_seconds
        self.failure_backoff_seconds = failure_backoff_seconds
        self.cache = caches["default"]

    def read(self, *, from_writer: bool = False) -> T | None:
        try:
            if from_writer and isinstance(self.cache, RedisCache):
                value = self.cache.client.get(self.key, client=get_redis_connection("default"))
            else:
                value = self.cache.get(self.key)
        except (ConnectionInterrupted, RedisError):
            logger.warning("Failed to read coalesced cache", key=self.key, exc_info=True)
            return None
        return cast(T, value) if self.is_valid(value) else None

    def _lock(self) -> Lock:
        # Redis Lock stores an owner token and only deletes or renews the lease when that token matches.
        return get_redis_connection("default").lock(
            self.cache.make_key(f"{self.key}:refresh"), timeout=self.lease_seconds
        )

    @staticmethod
    def _acquire(lock: Lock, token: str, wait: float | None = None) -> str:
        try:
            acquired = (
                lock.acquire(blocking=False, token=token)
                if wait is None
                else lock.acquire(blocking=True, blocking_timeout=wait, token=token)
            )
        except RedisError:
            logger.warning("Failed to acquire cache refresh claim", exc_info=True)
            return "redis_error"
        return "acquired" if acquired else "contended"

    @staticmethod
    def _renew(lock: Lock) -> bool:
        try:
            return lock.reacquire()
        except LockNotOwnedError:
            return False
        except RedisError:
            logger.warning("Could not confirm cache refresh claim renewal", exc_info=True)
            return True

    @staticmethod
    def _release(lock: Lock) -> None:
        try:
            lock.release()
        except RedisError:
            logger.warning("Cache refresh claim no longer owned", exc_info=True)

    def _publish(self, value: T, token: str) -> bool:
        cache_backend = self.cache
        if not isinstance(cache_backend, RedisCache):
            raise TypeError("CoalescedCacheRefresh requires the default Redis cache backend")
        try:
            return bool(
                get_redis_connection("default").eval(
                    _PUBLISH_IF_OWNER,
                    2,
                    cache_backend.make_key(f"{self.key}:refresh"),
                    cache_backend.make_key(self.key),
                    token,
                    cache_backend.client.encode(value),
                    self.timeout * 1000,
                )
            )
        except RedisError:
            logger.warning("Failed to publish coalesced cache", key=self.key, exc_info=True)
            return False

    def _backoff_active(self) -> bool:
        try:
            return bool(self.cache.get(f"{self.key}:refresh_failed"))
        except (ConnectionInterrupted, RedisError):
            return False

    def _record_failure(self) -> None:
        try:
            self.cache.set(f"{self.key}:refresh_failed", True, timeout=self.failure_backoff_seconds)
        except (ConnectionInterrupted, RedisError):
            logger.warning("Failed to record cache refresh backoff", key=self.key, exc_info=True)

    def get(self) -> T:
        span = trace.get_current_span()
        cached = self.read()
        stale = self.is_stale(cached)
        span.set_attribute("cache.refresh.result", "miss" if stale else "hit")
        span.set_attribute("cache.refresh.snapshot_present", cached is not None)
        if not stale:
            span.set_attribute("cache.refresh.state", "not_needed")
            assert cached is not None
            return cached
        if cached is not None and self._backoff_active():
            span.set_attribute("cache.refresh.state", "failure_backoff")
            return cached

        token = uuid.uuid4().hex
        try:
            lock = self._lock()
        except RedisError:
            logger.warning("Failed to create cache refresh claim", key=self.key, exc_info=True)
            lock = None
        claim = self._acquire(lock, token) if lock is not None else "redis_error"
        if claim == "contended" and cached is None:
            assert lock is not None
            claim = self._acquire(lock, token, self.cold_wait_seconds)
            if claim == "contended":
                filled = self.read(from_writer=True)
                if filled is not None:
                    span.set_attribute("cache.refresh.state", "filled_during_wait")
                    return filled
                span.set_attribute("cache.refresh.state", "cold_wait_timeout")
                raise CacheRefreshInProgress("Cache refresh already in progress")

        owned = claim == "acquired"
        try:
            if owned:
                assert lock is not None
                latest = self.read(from_writer=True)
                if not self.is_stale(latest):
                    span.set_attribute("cache.refresh.state", "filled_before_claim")
                    assert latest is not None
                    return latest
                cached = latest or cached
            elif cached is None:
                cached = self.read()

            span.set_attribute(
                "cache.refresh.state", "owner" if owned else "redis_error" if claim == "redis_error" else "in_progress"
            )
            if not owned and cached is not None:
                return cached
            try:
                value = self.refresh((lambda: self._renew(lock)) if lock is not None and owned else (lambda: True))
                if not owned or self._publish(value, token):
                    return value
                return self.read(from_writer=True) or cached or value
            except Exception:
                logger.warning("Failed to refresh coalesced cache", key=self.key, exc_info=True)
                if cached is None:
                    raise
                self._record_failure()
                return cached
        finally:
            if owned:
                assert lock is not None
                self._release(lock)
