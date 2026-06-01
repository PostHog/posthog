import threading
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec

from django.conf import settings
from django.core.cache import caches

import structlog
from django_redis.pool import ConnectionFactory
from prometheus_client import Counter, Histogram
from redis.cluster import RedisCluster

logger = structlog.get_logger(__name__)

QUERY_CACHE_ALIAS = "query_cache"

REDIS_CLUSTER_DISCOVERY_COUNTER = Counter(
    "posthog_redis_cluster_discovery_total",
    "Number of times a RedisCluster client was constructed, each triggering COMMAND + CLUSTER SLOTS topology discovery.",
)

REDIS_CLUSTER_DISCOVERY_DURATION = Histogram(
    "posthog_redis_cluster_discovery_duration_seconds",
    "Wall-clock time spent constructing a RedisCluster client, including COMMAND + CLUSTER SLOTS topology discovery.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

P = ParamSpec("P")


def instrument_cluster_discovery(fn: Callable[P, RedisCluster]) -> Callable[P, RedisCluster]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> RedisCluster:
        REDIS_CLUSTER_DISCOVERY_COUNTER.inc()
        with REDIS_CLUSTER_DISCOVERY_DURATION.time():
            return fn(*args, **kwargs)

    return wrapper


class RedisClusterConnectionFactory(ConnectionFactory):
    """ConnectionFactory for django_redis that creates RedisCluster connections.

    RedisCluster manages its own internal per-node connection pools, so we
    override connect() to use RedisCluster.from_url() instead of the default
    Redis(connection_pool=pool) pattern. RedisCluster inherits from Redis and
    implements the same command interface, so django_redis's DefaultClient
    (compression, serialization) works unchanged.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cluster_clients: dict[str, RedisCluster] = {}
        self._lock = threading.Lock()

    def connect(self, url: str) -> RedisCluster:
        if url not in self._cluster_clients:
            with self._lock:
                if url not in self._cluster_clients:
                    self._cluster_clients[url] = self._create_cluster_client(url)
        return self._cluster_clients[url]

    @instrument_cluster_discovery
    def _create_cluster_client(self, url: str) -> RedisCluster:
        return RedisCluster.from_url(url)

    def disconnect(self, connection) -> None:
        connection.close()


def prewarm_query_cache_cluster() -> None:
    """Force RedisCluster topology discovery during worker startup.

    Discovery (COMMAND + CLUSTER SLOTS) otherwise happens lazily on the worker's
    first cacheable query, putting it on a user's query critical path. Issuing a
    trivial read here moves it into warmup instead. Safe to call when the
    query_cache alias is not configured — it is a no-op then.
    """
    if QUERY_CACHE_ALIAS not in settings.CACHES:
        return
    try:
        caches[QUERY_CACHE_ALIAS].get("__prewarm__")
    except Exception:
        logger.warning("prewarm_query_cache_cluster_failure", exc_info=True)
