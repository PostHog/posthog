"""
A version number in the cache that a cached value puts in its key. A write bumps the version, so readers
build a new value and the old entries expire on their own TTL.
"""

from django.core.cache import cache

from posthog.utils import get_safe_cache


def read_cache_version(key: str, timeout: int) -> int:
    raw = get_safe_cache(key)
    if raw is None:
        try:
            cache.add(key, 0, timeout=timeout)
        except Exception:
            pass
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def bump_cache_version(key: str, timeout: int) -> None:
    try:
        cache.incr(key)
        # incr keeps the old expiry. If the key expired, the version would start again at 0 and could
        # match entries that are still cached.
        cache.touch(key, timeout=timeout)
    except ValueError:
        try:
            cache.add(key, 1, timeout=timeout)
        except Exception:
            pass
    except Exception:
        pass
