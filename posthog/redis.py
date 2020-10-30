from typing import Optional

import fakeredis  # type: ignore
import redis
from django.conf import settings

_client = None  # type: Optional[redis.Redis]


def get_client() -> redis.Redis:
    global _client

    if _client:
        return _client

    if settings.TEST:
        _client = fakeredis.FakeStrictRedis()
    elif settings.REDIS_URL:
        _client = redis.from_url(settings.REDIS_URL, db=0)

    if not _client:
        raise Exception("Redis not configured!")

    return _client
