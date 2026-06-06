import threading

from django.conf import settings
from django.core.cache import caches

import structlog
from django_redis.pool import ConnectionFactory
from opentelemetry import trace
from redis.cluster import RedisCluster

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

QUERY_CACHE_ALIAS = "query_cache"


class RedisClusterConnectionFactory(ConnectionFactory):
    """ConnectionFactory for django_redis that creates RedisCluster connections.

    RedisCluster manages its own internal per-node connection pools, so we
    override connect() to use RedisCluster.from_url() instead of the default
    Redis(connection_pool=pool) pattern. RedisCluster inherits from Redis and
    implements the same command interface, so django_redis's DefaultClient
    (compression, serialization) works unchanged.

    Constructing a RedisCluster issues COMMAND + CLUSTER SLOTS topology
    discovery. We wrap that construction in a "redis_cluster.discovery" span so
    its place in a trace is visible: nested under a request span means discovery
    is on a user's critical path; a parentless span means it ran during warmup.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cluster_clients: dict[str, RedisCluster] = {}
        self._lock = threading.Lock()

    def connect(self, url: str) -> RedisCluster:
        if url not in self._cluster_clients:
            with self._lock:
                if url not in self._cluster_clients:
                    self._cluster_clients[url] = self._discover_cluster(url)
        return self._cluster_clients[url]

    @tracer.start_as_current_span("redis_cluster.discovery")
    def _discover_cluster(self, url: str) -> RedisCluster:
        return RedisCluster.from_url(url)

    def disconnect(self, connection) -> None:
        connection.close()


def prewarm_query_cache_cluster() -> None:
    """Force RedisCluster topology discovery during worker warmup.

    Discovery (COMMAND + CLUSTER SLOTS) otherwise happens lazily on the worker's
    first cacheable query, putting it on a user's query critical path. Issuing a
    trivial read here moves it earlier: to module import under WSGI, and to a
    background thread spawned from the post-fork init hook under ASGI (so it never
    blocks the event loop). Safe to call when the query_cache alias is not
    configured — it is a no-op then.
    """
    if QUERY_CACHE_ALIAS not in settings.CACHES:
        return
    try:
        caches[QUERY_CACHE_ALIAS].get("__prewarm__")
    except Exception:
        logger.warning("prewarm_query_cache_cluster_failure", exc_info=True)


def prewarm_query_cache_cluster_in_background() -> threading.Thread:
    """Run prewarm_query_cache_cluster() on a daemon thread.

    Callers on an event loop (the ASGI post-fork hook) must not run the blocking
    cluster discovery inline. prewarm_query_cache_cluster swallows and logs its
    own failures, so the thread cannot raise into the interpreter; daemon=True
    keeps a still-running warmup from delaying shutdown. Start this only after
    fork — never at module import on a server that forks workers.
    """
    thread = threading.Thread(
        target=prewarm_query_cache_cluster,
        name="prewarm-query-cache-cluster",
        daemon=True,
    )
    thread.start()
    return thread
