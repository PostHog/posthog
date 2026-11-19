import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

from unittest import SkipTest

from django.conf import settings

from redis.connection import parse_url

from posthog.caching.throttle_history_cache import throttle_history_cache


def unique_key_prefix(name: str) -> str:
    return f"{name}-{uuid4().hex}"


def lagging_reader_caches(key_prefix: str, primary_location: str | None = None) -> dict[str, Any]:
    primary = urlsplit(settings.REDIS_URL)
    own_db = int(parse_url(settings.REDIS_URL).get("db", 0))
    workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    free_dbs = [db for db in (15, 14) if db != own_db and db >= workers]
    if not free_dbs:
        raise SkipTest("every Redis database belongs to a test worker, so none can stand in for a lagging reader")
    reader_db = free_dbs[0]
    query = [(name, value) for name, value in parse_qsl(primary.query) if name != "db"]
    reader = f"{primary.scheme}://{primary.netloc}{primary.path}?" + urlencode([*query, ("db", str(reader_db))])
    default = {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": [primary_location or settings.REDIS_URL, reader],
        "KEY_PREFIX": key_prefix,
    }
    return {"default": default, "throttle_history": throttle_history_cache(default)}
