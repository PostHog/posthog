import fakeredis
import redis
from django.conf import settings

redis_instance = None

if settings.TEST:
    redis_instance = fakeredis.FakeStrictRedis()
elif settings.REDIS_URL:
    redis_instance = redis.from_url(settings.REDIS_URL, db=0)


def get_cache_key(key: str):
    return redis_instance.get(key)


def set_cache_key(key: str, value: str):
    return redis_instance.set(key, value)


def clear_cache():
    if not settings.TEST and not settings.DEBUG:
        raise ("Can only clear redis cache in TEST or DEBUG mode!")

    redis_instance.flushdb()
