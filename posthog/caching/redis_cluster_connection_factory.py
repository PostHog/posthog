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

    Discovered clients are cached at class scope (process-global), mirroring
    django_redis's ConnectionFactory._pools. Django builds a new cache client --
    and therefore a new factory instance -- per request, and `caches` is
    thread-local, so per-instance state would be discarded constantly and every
    request thread would re-run discovery. Class-level state is shared across all
    instances, so discovery runs once per process and the post-fork prewarm
    populates the same client the request threads read.
    """

    # Process-global cache of discovered cluster clients, keyed by URL. Must not
    # be per-instance -- see the class docstring.
    _cluster_clients: dict[str, RedisCluster] = {}
    _lock = threading.Lock()

    def connect(self, url: str) -> RedisCluster:
        client = self._cluster_clients.get(url)
        if client is None:
            with self._lock:
                client = self._cluster_clients.get(url)
                if client is None:
                    client = self._discover_cluster(url)
                    self._cluster_clients[url] = client
        return client

    @tracer.start_as_current_span("redis_cluster.discovery")
    def _discover_cluster(self, url: str) -> RedisCluster:
        # socket_keepalive keeps the long-lived pooled connections healthy across
        # idle periods, so an LB/NAT idle-timeout can't silently drop them and
        # force a reconnect (and fresh discovery) mid-request.
        return RedisCluster.from_url(url, socket_keepalive=True)

    def disconnect(self, connection) -> None:
        # The client is process-global, so evict it before closing -- otherwise
        # the cache would keep handing out a closed client. A no-op in the default
        # config (CLOSE_CONNECTION is unset, so django_redis never calls this per
        # request), but keeps the shared cache consistent if it is ever enabled.
        with self._lock:
            for url, client in list(self._cluster_clients.items()):
                if client is connection:
                    del self._cluster_clients[url]
                    break
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
