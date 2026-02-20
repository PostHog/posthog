from typing import NamedTuple, Union

from django.conf import settings
from django.core.cache import BaseCache, cache, caches

import posthoganalytics
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


def use_cluster_cache(team_id: int) -> bool:
    if QUERY_CACHE_ALIAS not in settings.CACHES:
        return False
    return posthoganalytics.feature_enabled(
        "query-cache-cluster-migration",
        str(team_id),
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def get_query_cache(team_id: int):
    if use_cluster_cache(team_id):
        return caches[QUERY_CACHE_ALIAS]
    return cache


def get_query_cache_selection(team_id: int) -> QueryCacheSelection:
    if use_cluster_cache(team_id):
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
