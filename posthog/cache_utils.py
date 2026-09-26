import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, ParamSpec, TypeVar, cast

from django.utils.timezone import now

import orjson
import structlog
from django_redis.serializers.base import BaseSerializer
from rest_framework.utils.encoders import JSONEncoder

from posthog.settings import TEST

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

CacheKey = tuple[tuple[Any, ...], frozenset[tuple[Any, Any]]]

MAX_REFRESH_BACKOFF = timedelta(minutes=1)


@dataclass(frozen=False)
class CachedFunction(Generic[P, R]):
    _fn: Callable[P, R]
    _cache_time: timedelta
    _background_refresh: bool = False

    _cache: dict[CacheKey, tuple[datetime, R]] = field(default_factory=dict, init=False, repr=False)
    _refreshing: dict[CacheKey, datetime | None] = field(default_factory=dict, init=False, repr=False)
    _refresh_failed_at: dict[CacheKey, datetime] = field(default_factory=dict, init=False, repr=False)
    # Guards the bookkeeping dicts. It is never held while the wrapped function runs.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def _refresh_is_backed_off(self, key: CacheKey, current_time: datetime) -> bool:
        failed_at = self._refresh_failed_at.get(key)
        if failed_at is None:
            return False
        return current_time - failed_at < min(self._cache_time, MAX_REFRESH_BACKOFF)

    def _claim_background_refresh(self, key: CacheKey, current_time: datetime) -> bool:
        # Two callers can pass an unguarded check together and each start a refresh of the same key.
        with self._lock:
            if self._refreshing.get(key) or self._refresh_is_backed_off(key, current_time):
                return False
            self._refreshing[key] = current_time
            return True

    def __call__(self, *args: Any, **kwargs: Any) -> R:
        use_cache = cast(bool, kwargs.pop("use_cache", not TEST))
        if not use_cache:
            return self._fn(*args, **kwargs)

        current_time = now()
        key: CacheKey = (args, frozenset(sorted(kwargs.items())))

        def refresh(in_background: bool) -> None:
            try:
                value = self._fn(*args, **kwargs)
            except Exception:
                with self._lock:
                    if in_background:
                        self._refresh_failed_at[key] = now()
                    self._refreshing[key] = None
                if not in_background:
                    raise
                # The caller already has the previously cached value, so there is nobody to raise to.
                logger.exception("cache_for_background_refresh_failed", fn=getattr(self._fn, "__qualname__", None))
                return

            with self._lock:
                self._cache[key] = (now(), value)
                self._refresh_failed_at.pop(key, None)
                self._refreshing[key] = None

        if key not in self._cache:
            refresh(in_background=False)
        elif current_time - self._cache[key][0] > self._cache_time:
            if self._background_refresh:
                if self._claim_background_refresh(key, current_time):
                    t = threading.Thread(
                        target=refresh,
                        kwargs={"in_background": True},
                        name="cache-for-background-refresh",
                        daemon=True,
                    )
                    t.start()
            else:
                refresh(in_background=False)

        return self._cache[key][1]

    def clear_cache(self) -> None:
        """Drop all in-process cache entries. Intended for tests that need to start
        with a clean slate; production callers should rely on the TTL instead."""
        self._cache.clear()
        self._refreshing.clear()
        self._refresh_failed_at.clear()


def cache_for(cache_time: timedelta, background_refresh=False) -> Callable[[Callable[P, R]], CachedFunction[P, R]]:
    def wrapper(fn: Callable[P, R]) -> CachedFunction[P, R]:
        return CachedFunction(fn, cache_time, background_refresh)

    return wrapper


def instance_memoize(callback):
    name = f"_{callback.__name__}_memo"

    def _inner(self, *args):
        if not hasattr(self, name):
            setattr(self, name, {})

        memo = getattr(self, name)
        if args not in memo:
            memo[args] = callback(self, *args)
        return memo[args]

    return _inner


class OrjsonJsonSerializer(BaseSerializer):
    def dumps(self, value: Any) -> bytes:
        option = orjson.OPT_UTC_Z
        return orjson.dumps(value, default=JSONEncoder().default, option=option)

    def loads(self, value: bytes) -> Any:
        return orjson.loads(value)
