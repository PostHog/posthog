from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

from django.conf import settings

from redis.connection import parse_url


def unique_key_prefix(name: str) -> str:
    return f"{name}-{uuid4().hex}"


def lagging_reader_caches(key_prefix: str, primary_location: str | None = None) -> dict[str, Any]:
    primary = urlsplit(settings.REDIS_URL)
    reader_db = 14 if int(parse_url(settings.REDIS_URL).get("db", 0)) == 15 else 15
    query = [(name, value) for name, value in parse_qsl(primary.query) if name != "db"]
    reader = f"{primary.scheme}://{primary.netloc}{primary.path}?" + urlencode([*query, ("db", str(reader_db))])
    return {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": [primary_location or settings.REDIS_URL, reader],
            "KEY_PREFIX": key_prefix,
        },
        "throttle_history": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": primary_location or settings.REDIS_URL,
            "KEY_PREFIX": key_prefix,
            "OPTIONS": {"SOCKET_CONNECT_TIMEOUT": 0.2, "SOCKET_TIMEOUT": 0.2},
        },
    }
