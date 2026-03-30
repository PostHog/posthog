from typing import NamedTuple, Union

from django.conf import settings
from django.core.cache import BaseCache, cache, caches

from django_redis import get_redis_connection
from redis import Redis, RedisCluster

from posthog import redis

QUERY_CACHE_ALIAS = "query_cache"

BACKEND_CLUSTER = "cluster"
BACKEND_DEFAULT = "default"


class QueryCacheSelection(NamedTuple):
    cache_backend: BaseCache
    redis_client: Union[Redis, RedisCluster]
    is_cluster: bool


def use_cluster_cache() -> bool:
    return QUERY_CACHE_ALIAS in settings.CACHES


def get_query_cache():
    if use_cluster_cache():
        return caches[QUERY_CACHE_ALIAS]
    return cache


def get_query_cache_selection() -> QueryCacheSelection:
    if use_cluster_cache():
        return QueryCacheSelection(
            cache_backend=caches[QUERY_CACHE_ALIAS],
            redis_client=get_redis_connection(QUERY_CACHE_ALIAS),
            is_cluster=True,
        )

    return QueryCacheSelection(
        cache_backend=cache,
        redis_client=redis.get_client(),
        is_cluster=False,
    )
