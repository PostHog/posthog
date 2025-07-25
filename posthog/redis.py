# flake8: noqa
from typing import Any, Dict, Optional

import asyncio
import weakref

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import redis
from redis import asyncio as aioredis


_client_map: Dict[str, Any] = {}
_test_async_client_map: Dict[str, Any] = {}  # For test mode, where we don't need per-loop isolation


def get_client(redis_url: Optional[str] = None) -> redis.Redis:
    """Return a *synchronous* Redis client (singleton per redis_url)."""

    redis_url = redis_url or settings.REDIS_URL
    if redis_url is None:
        raise ImproperlyConfigured("REDIS_URL is not configured")

    if not _client_map.get(redis_url):
        if settings.TEST:
            # This import is only used in tests, we don't want to import it in production
            import fakeredis

            client: Any = fakeredis.FakeRedis()
        elif redis_url:
            client = redis.from_url(redis_url, db=0)
        else:
            client = None

        if client is None:
            raise ImproperlyConfigured("Redis not configured!")

        _client_map[redis_url] = client

    return _client_map[redis_url]


_loop_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, Any]]" = weakref.WeakKeyDictionary()


def _close_pools(pool_map: Dict[str, Any]) -> None:
    """Close all Redis pools that belonged to a dead event-loop."""

    for client in pool_map.values():
        try:
            # For async clients, close() returns a coroutine
            close_method = getattr(client, "close", None)
            if close_method:
                result = close_method(close_connection_pool=True)
                # If it's a coroutine, we need to run it in an event loop
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(result)
                        loop.close()
                    except Exception:
                        pass
        except Exception:  # close shouldn't fail, but be safe
            pass


def get_async_client(redis_url: Optional[str] = None):
    """Return an *async* Redis client bound to *this* event-loop.

    This is safe when multiple :pyclass:`asyncio.AbstractEventLoop` objects exist in the
    same Python process (that happens anytime someone calls
    :pyfunc:`asyncio.run`, which we unfortunately do in a few endpoints and
    management commands).
    It does not leak file-descriptors or memory when those short-lived event-loops
    disappear.

    The synchronous helper (`get_client`) is trivial – we can keep a single process-wide
    singleton.  The asynchronous side is trickier because an ``aioredis.Redis``
    instance is bound to the event-loop in which it was created. Using the same
    client from another loop raises

    ``RuntimeError: Task ... got Future attached to a different loop``.

    To make this bullet-proof we cache one Redis instance
    per (event-loop, redis_url) pair and keep that cache in a
    ``weakref.WeakKeyDictionary``. When a loop is garbage-collected (which happens
    immediately after ``asyncio.run`` returns) its entry in the weak dict
    disappears and we close all the connection pools via a ``weakref.finalize``.

    This gives us:

    * zero cross-loop accidents (each pool is only ever used by the loop that
      created it),
    * zero leaks (pools are closed as soon as their loop dies),
    * no behavioural change for callers (they still just call
      :pyfunc:`get_async_client`).

    If you *really* need to bypass the cache, just call ``aioredis.from_url``
    directly; but in 99 % of cases you want the cached client.
    """

    redis_url = redis_url or settings.REDIS_URL
    if redis_url is None:
        raise ImproperlyConfigured("REDIS_URL is not configured")

    if settings.TEST:
        # For tests, use simple URL-based caching without per-loop complexity
        # This allows tests to work both inside and outside async contexts
        if redis_url not in _test_async_client_map:
            import fakeredis

            _test_async_client_map[redis_url] = fakeredis.FakeAsyncRedis()
        return _test_async_client_map[redis_url]
    else:
        # Production code: use per-loop caching for real Redis connections
        loop = asyncio.get_running_loop()

        # Get (or create) the per-loop sub-map
        pool_map = _loop_clients.get(loop)
        if pool_map is None:
            pool_map = {}
            _loop_clients[loop] = pool_map
            # As soon as loop is garbage collected call _close_pools(pool_map)
            weakref.finalize(loop, _close_pools, pool_map)

        # Get (or create) the Redis instance for redis_url
        client = pool_map.get(redis_url)
        if client is None:
            client = aioredis.from_url(redis_url, db=0)
            pool_map[redis_url] = client

        return client


def TEST_clear_clients():
    global _client_map
    for key in list(_client_map.keys()):
        del _client_map[key]
    global _test_async_client_map
    for key in list(_test_async_client_map.keys()):
        del _test_async_client_map[key]
    global _loop_clients
    for loop in list(_loop_clients.keys()):
        del _loop_clients[loop]
