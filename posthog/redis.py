# flake8: noqa
from typing import Any, Dict, Optional, TypeVar, Union, overload

import redis
from redis import asyncio as aioredis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_client_map: Dict[str, Any] = {}
_async_client_map: Dict[str, Any] = {}


def get_client(redis_url: Optional[str] = None) -> redis.Redis:
    redis_url = redis_url or settings.REDIS_URL

    global _client_map

    if not _client_map.get(redis_url):
        client: Any = None

        if settings.TEST:
            import fakeredis

            client = fakeredis.FakeRedis()
        elif redis_url:
            client = redis.from_url(redis_url, db=0)

        if not client:
            raise ImproperlyConfigured("Redis not configured!")

        _client_map[redis_url] = client

    return _client_map[redis_url]


def get_async_client(redis_url: Optional[str] = None) -> aioredis.Redis:
    redis_url = redis_url or settings.REDIS_URL

    global _async_client_map

    if not _async_client_map.get(redis_url):
        client: Any = None

        if settings.TEST:
            import fakeredis

            client = fakeredis.FakeAsyncRedis()
        elif redis_url:
            client = aioredis.from_url(redis_url, db=0)

        if not client:
            raise ImproperlyConfigured("Redis not configured!")

        _async_client_map[redis_url] = client

    return _async_client_map[redis_url]


def TEST_clear_clients():
    global _client_map, _async_client_map
    for key in list(_client_map.keys()):
        del _client_map[key]
    for key in list(_async_client_map.keys()):
        del _async_client_map[key]
