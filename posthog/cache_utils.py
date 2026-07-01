import functools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, ParamSpec, TypeVar, cast

from django.utils.timezone import now

import orjson
import structlog
import redis.exceptions
from django_redis.serializers.base import BaseSerializer
from rest_framework.utils.encoders import JSONEncoder

from posthog.settings import TEST

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

CacheKey = tuple[tuple[Any, ...], frozenset[tuple[Any, Any]]]

# Transient Redis connectivity blips (master failover, brief outage) are infrastructure noise,
# not code defects. On a background refresh the last cached value is still being served, so these
# are logged and skipped rather than raised — letting them escape the daemon thread would capture
# a spurious error-tracking issue on every Redis hiccup. Genuine bugs still surface as before.
TRANSIENT_REDIS_ERRORS = (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)


@dataclass()
class CachedFunction(Generic[P, R]):
    _fn: Callable[P, R]
    _cache_time: timedelta
    _background_refresh: bool = False

    _cache: dict[CacheKey, tuple[datetime, R]] = field(default_factory=dict, init=False, repr=False)
    _refreshing: dict[CacheKey, datetime | None] = field(default_factory=dict, init=False, repr=False)

    def __call__(self, *args: Any, **kwargs: Any) -> R:
        use_cache = cast(bool, kwargs.pop("use_cache", not TEST))
        if not use_cache:
            return self._fn(*args, **kwargs)

        current_time = now()
        key: CacheKey = (args, frozenset(sorted(kwargs.items())))

        def refresh(background: bool = False):
            try:
                value = self._fn(*args, **kwargs)
                self._cache[key] = (now(), value)
                self._refreshing[key] = None
            except TRANSIENT_REDIS_ERRORS as e:
                self._refreshing[key] = None
                # A background refresh runs on a daemon thread with no caller to handle the error,
                # and a previously cached value is still being served, so log and skip. On the
                # synchronous path there is no fallback, so let the error propagate to the caller.
                if not background:
                    raise
                logger.warning(
                    "cache_for background refresh hit a transient Redis error; serving stale cached value",
                    fn=getattr(self._fn, "__name__", repr(self._fn)),
                    error=str(e),
                )
            except Exception:
                self._refreshing[key] = None
                raise

        if key not in self._cache:
            refresh()
        elif current_time - self._cache[key][0] > self._cache_time:
            if self._background_refresh:
                if not self._refreshing.get(key):
                    self._refreshing[key] = current_time
                    t = threading.Thread(target=functools.partial(refresh, background=True))
                    t.start()
            else:
                refresh()

        return self._cache[key][1]

    def clear_cache(self) -> None:
        """Drop all in-process cache entries. Intended for tests that need to start
        with a clean slate; production callers should rely on the TTL instead."""
        self._cache.clear()
        self._refreshing.clear()


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
