import os
import threading

from django.conf import settings
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured

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

    A RedisCluster holds open sockets, so it must not cross a fork: a client
    discovered before fork (e.g. by a pre-fork prewarm) would be inherited by
    every worker, sharing the same file descriptors across processes. connect()
    guards against this by binding the cache to the pid that filled it and
    rediscovering after a fork.

    This relies on the client being long-lived, so CLOSE_CONNECTION is
    unsupported on this alias and rejected in __init__: django_redis closes
    connections per request when it is set, which would tear down and rediscover
    the shared client on every request -- the exact per-request discovery this
    class exists to avoid.
    """

    # Class scope (process-global), not per-instance -- see the class docstring.
    _cluster_clients: dict[str, RedisCluster] = {}
    _lock = threading.Lock()
    _owner_pid: int | None = None

    def __init__(self, options: dict) -> None:
        super().__init__(options)
        close_connection = options.get("CLOSE_CONNECTION", getattr(settings, "DJANGO_REDIS_CLOSE_CONNECTION", False))
        if close_connection:
            raise ImproperlyConfigured(
                "CLOSE_CONNECTION is not supported on a RedisClusterConnectionFactory alias: "
                "the cluster client is shared process-wide and long-lived, so closing it per "
                "request would force topology rediscovery on every request."
            )

    def connect(self, url: str) -> RedisCluster:
        pid = os.getpid()
        client = self._cluster_clients.get(url) if self._owner_pid == pid else None
        if client is None:
            with self._lock:
                if self._owner_pid != pid:
                    # Crossed a fork: the inherited clients hold the parent's
                    # sockets. Drop them and rediscover in this process.
                    self._cluster_clients.clear()
                    RedisClusterConnectionFactory._owner_pid = pid
                client = self._cluster_clients.get(url)
                if client is None:
                    client = self._discover_cluster(url)
                    self._cluster_clients[url] = client
        return client

    @tracer.start_as_current_span("redis_cluster.discovery")
    def _discover_cluster(self, url: str) -> RedisCluster:
        # socket_keepalive enables TCP keepalive on the long-lived pooled
        # connections -- best-effort protection against an idle LB/NAT silently
        # dropping them and forcing a reconnect (and fresh discovery) mid-request.
        # With OS-default keepalive timing this isn't a hard guarantee; tune
        # socket_keepalive_options below the real idle timeout if drops persist.
        return RedisCluster.from_url(url, socket_keepalive=True)


def prewarm_query_cache_cluster() -> None:
    """Force RedisCluster topology discovery during worker warmup.

    Discovery (COMMAND + CLUSTER SLOTS) otherwise happens lazily on the worker's
    first cacheable query, putting it on a user's query critical path. Both
    wsgi.py and asgi.py call this (via the background helper) from a first-request
    post-fork hook, so discovery runs in the worker process and is warm before the
    first real query. Safe to call when the query_cache alias is not configured —
    it is a no-op then.
    """
    if QUERY_CACHE_ALIAS not in settings.CACHES:
        return
    try:
        caches[QUERY_CACHE_ALIAS].get("__prewarm__")
    except Exception:
        logger.warning("prewarm_query_cache_cluster_failure", exc_info=True)


def prewarm_query_cache_cluster_in_background() -> threading.Thread:
    """Run prewarm_query_cache_cluster() on a daemon thread.

    The first-request post-fork hooks (wsgi.py and asgi.py) use this so the
    blocking cluster discovery never runs inline -- it would block the ASGI event
    loop, and needlessly delay the first WSGI request. prewarm_query_cache_cluster
    swallows and logs its own failures, so the thread cannot raise into the
    interpreter; daemon=True keeps a still-running warmup from delaying shutdown.
    Start this only after fork — never at module import on a server that forks
    workers.
    """
    thread = threading.Thread(
        target=prewarm_query_cache_cluster,
        name="prewarm-query-cache-cluster",
        daemon=True,
    )
    thread.start()
    return thread
