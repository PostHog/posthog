from dataclasses import dataclass, field
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Generic, ParamSpec, TypeVar

import orjson
from rest_framework.utils.encoders import JSONEncoder
from django.utils.timezone import now
from django_redis.serializers.base import BaseSerializer

from posthog.settings import TEST

P = ParamSpec("P")
R = TypeVar("R")

CacheKey = tuple[tuple[Any, ...], frozenset[tuple[Any, Any]]]


@dataclass(slots=True)
class CachedFunction(Generic[P, R]):
    _fn: Callable[P, R]
    _cache_time: timedelta
    _background_refresh: bool = False

    _cache: dict[CacheKey, tuple[datetime, R]] = field(default_factory=dict, init=False, repr=False)
    _refreshing: dict[CacheKey, datetime | None] = field(default_factory=dict, init=False, repr=False)

    def __call__(self, *args: P.args, use_cache: bool = not TEST, **kwargs: P.kwargs) -> R:
        if not use_cache:
            return self._fn(*args, **kwargs)

        current_time = now()
        key: CacheKey = (args, frozenset(sorted(kwargs.items())))

        def refresh():
            try:
                value = self._fn(*args, **kwargs)
                self._cache[key] = (now(), value)
                self._refreshing[key] = None
            except Exception:
                self._refreshing[key] = None
                raise

        if key not in self._cache:
            refresh()
        elif current_time - self._cache[key][0] > self._cache_time:
            if self._background_refresh:
                if not self._refreshing.get(key):
                    self._refreshing[key] = current_time
                    t = threading.Thread(target=refresh)
                    t.start()
            else:
                refresh()

        return self._cache[key][1]


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
