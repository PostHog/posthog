from datetime import timedelta
from functools import wraps
from typing import no_type_check

from django.utils.timezone import now

from posthog.settings import TEST


def cache_for(cache_time: timedelta):
    def wrapper(fn):
        @wraps(fn)
        @no_type_check
        def memoized_fn(*args, use_cache=not TEST):
            if not use_cache:
                return fn(*args)

            current_time = now()
            if args not in memoized_fn._cache or current_time - memoized_fn._cache[args][0] > cache_time:
                memoized_fn._cache[args] = (current_time, fn(*args))
            return memoized_fn._cache[args][1]

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
