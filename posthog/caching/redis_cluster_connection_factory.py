import threading

from django.conf import settings
from django.core.cache import caches

import structlog
from django_redis.pool import ConnectionFactory
from redis.cluster import RedisCluster

logger = structlog.get_logger(__name__)


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
                    self._cluster_clients[url] = RedisCluster.from_url(url)
        return self._cluster_clients[url]

    def disconnect(self, connection) -> None:
        connection.close()


def warm_query_cache_connection() -> None:
    """
    Force the query_cache RedisCluster client to instantiate at worker startup
    so the first user request doesn't pay the CLUSTER SLOTS + COMMAND handshake.

    Idempotent — django_redis caches the client per process after first use.
    Safe to call before any request lands; the cluster client and its
    per-node pools are created post-fork in WSGI (wsgi.py is imported per
    worker) and post-spawn in Granian, so connection state isn't shared
    across workers.
    """
    if settings.TEST or settings.STATIC_COLLECTION:
        return
    if "query_cache" not in settings.CACHES:
        return

    try:
        caches["query_cache"].get("__startup_warmup__")
    except Exception:
        logger.warning("query_cache_warmup_failure", exc_info=True)
