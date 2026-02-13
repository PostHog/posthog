from typing import NamedTuple

from django.conf import settings
from django.core.cache import cache, caches

import posthoganalytics

from posthog import redis

QUERY_CACHE_ALIAS = "query_cache"

BACKEND_CLUSTER = "cluster"
BACKEND_DEFAULT = "default"


class QueryCacheSelection(NamedTuple):
    cache_backend: object
    redis_client: object


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
        query_cache = caches[QUERY_CACHE_ALIAS]
        return QueryCacheSelection(
            cache_backend=query_cache,
            redis_client=query_cache.client.get_client(write=True),
        )

    return QueryCacheSelection(
        cache_backend=cache,
        redis_client=redis.get_client(),
    )
