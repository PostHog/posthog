# flake8: noqa
from typing import Any, Dict, Optional, TypeVar, Union, overload

import redis
from redis import asyncio as aioredis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_client_map: Dict[str, Any] = {}

T = TypeVar("T", redis.Redis, aioredis.Redis)


def _get_client_impl(redis_url: str, is_async: bool) -> Any:
    """Internal implementation for getting Redis clients."""
    if not _client_map.get(redis_url):
        client: Any = None

        if settings.TEST:
            import fakeredis

            client = fakeredis.FakeAsyncRedis() if is_async else fakeredis.FakeRedis()
        elif redis_url:
            client = aioredis.from_url(redis_url, db=0) if is_async else redis.from_url(redis_url, db=0)

        if not client:
            raise ImproperlyConfigured("Redis not configured!")

        _client_map[redis_url] = client

    return _client_map[redis_url]


def get_client(redis_url: Optional[str] = None) -> redis.Redis:
    redis_url = redis_url or settings.REDIS_URL
    return _get_client_impl(redis_url, is_async=False)


def get_async_client(redis_url: Optional[str] = None) -> aioredis.Redis:
    redis_url = redis_url or settings.REDIS_URL
    return _get_client_impl(redis_url, is_async=True)


def TEST_clear_clients():
    global _client_map
    for key in list(_client_map.keys()):
        del _client_map[key]
