from datetime import timedelta
from functools import wraps
from typing import Optional, no_type_check

from django.core.cache import cache
from django.utils.timezone import now

from posthog.settings import TEST


def cache_for(
    cache_time: timedelta, redis_cache_key: Optional[str] = None, redis_cache_time: Optional[timedelta] = None
):
    """
    Allows caching function both in-memory and in redis.

    Constraints:
    - Function must not take arguments or return None for redis caching.
    """

    def wrapper(fn):
        @wraps(fn)
        @no_type_check
        def memoized_fn(*args, use_cache=not TEST, **kwargs):
            if not use_cache:
                return fn(*args, **kwargs)

            current_time = now()
            key = (args, frozenset(sorted(kwargs.items())))

            if key in memoized_fn._cache and current_time - memoized_fn._cache[key][0] <= cache_time:
                return memoized_fn._cache[key][1]

            assert redis_cache_key is None or (len(args) == 0 and len(kwargs) == 0)

            result = None
            calculate_result_needed = True
            if redis_cache_key is not None:
                result = cache.get(redis_cache_key)
                calculate_result_needed = result is None

            if calculate_result_needed:
                result = fn(*args, **kwargs)

            memoized_fn._cache[key] = (current_time, result)
            if calculate_result_needed and redis_cache_key is not None:
                assert result is not None
                assert redis_cache_time is not None
                cache.set(key, result, timeout=redis_cache_time.total_seconds())

            return result

        memoized_fn._cache = {}
        return memoized_fn

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
