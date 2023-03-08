import threading
from datetime import timedelta
from functools import wraps
from typing import no_type_check

from django.utils.timezone import now

from posthog.settings import TEST


def cache_for(cache_time: timedelta, background_refresh=False):
    def wrapper(fn):
        @wraps(fn)
        @no_type_check
        def memoized_fn(*args, use_cache=not TEST, **kwargs):
            if not use_cache:
                return fn(*args, **kwargs)

            current_time = now()
            key = (args, frozenset(sorted(kwargs.items())))

            def refresh():
                try:
                    value = fn(*args, **kwargs)
                    memoized_fn._cache[key] = (now(), value)
                    memoized_fn._refreshing[key] = None
                except Exception:
                    memoized_fn._refreshing[key] = None
                    raise

            if key not in memoized_fn._cache:
                refresh()
            elif current_time - memoized_fn._cache[key][0] > cache_time:
                if background_refresh:
                    if not memoized_fn._refreshing.get(key):
                        memoized_fn._refreshing[key] = current_time
                        t = threading.Thread(target=refresh)
                        t.start()
                else:
                    refresh()

            return memoized_fn._cache[key][1]

        memoized_fn._cache = {}
        memoized_fn._refreshing = {}
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
