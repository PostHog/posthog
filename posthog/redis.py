# flake8: noqa
from typing import Optional

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_client = None  # type: Optional[redis.Redis]


def get_client(redis_url=settings.REDIS_URL) -> redis.Redis:
    global _client

    if _client:
        return _client

    if settings.TEST:
        import fakeredis

        _client = fakeredis.FakeRedis()
    elif redis_url:
        _client = redis.from_url(redis_url, db=0)

    if not _client:
        raise ImproperlyConfigured("Redis not configured!")

    return _client
