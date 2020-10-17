from typing import Optional

import fakeredis  # type: ignore
import redis
from django.conf import settings

redis_instance = None  # type: Optional[redis.Redis]


def get_redis_instance() -> redis.Redis:
    global redis_instance

    if redis_instance:
        return redis_instance

    if settings.TEST:
        redis_instance = fakeredis.FakeStrictRedis()
    elif settings.REDIS_URL:
        redis_instance = redis.from_url(settings.REDIS_URL, db=0)

    if not redis_instance:
        raise Exception("Redis not configured!")

    return redis_instance


def get_cache_key(team_id: int, key: str) -> str:
    return "@c/{}/{}".format(team_id, key)


def get_cached_value(team_id: int, key: str) -> Optional[str]:
    return get_redis_instance().get(get_cache_key(team_id, key))


def set_cached_value(team_id: int, key: str, value: str) -> None:
    get_redis_instance().set(get_cache_key(team_id, key), value)


def clear_cache() -> None:
    if not settings.TEST and not settings.DEBUG:
        raise Exception("Can only clear redis cache in TEST or DEBUG mode!")
    get_redis_instance().flushdb()
