from typing import Optional

import redis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_client = None  # type: Optional[redis.Redis]


def get_client() -> redis.Redis:
    global _client

    if _client:
        return _client

    if settings.TEST:
        import fakeredis

        _client = fakeredis.FakeRedis()
    elif settings.REDIS_URL:
        _client = redis.from_url(settings.REDIS_URL, db=0)

    if not _client:
        raise ImproperlyConfigured("Redis not configured!")

    return _client
