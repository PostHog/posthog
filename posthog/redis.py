# flake8: noqa
from typing import Dict, Optional

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_client_map: Dict[str, redis.Redis] = {}


def get_client(redis_url: Optional[str] = None) -> redis.Redis:
    redis_url = redis_url or settings.REDIS_URL

    global _client_map

    if not _client_map.get(redis_url):
        if settings.TEST:
            import fakeredis

            client = fakeredis.FakeRedis()  # type: ignore
        elif redis_url:
            client = redis.from_url(redis_url, db=0)

        if not client:
            raise ImproperlyConfigured("Redis not configured!")

        _client_map[redis_url] = client

    return _client_map[redis_url]


def TEST_clear_clients():
    global _client_map
    for key in list(_client_map.keys()):
        del _client_map[key]
