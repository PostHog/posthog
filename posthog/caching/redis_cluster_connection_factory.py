from django_redis.pool import ConnectionFactory
from redis.cluster import RedisCluster


class RedisClusterConnectionFactory(ConnectionFactory):
    """ConnectionFactory for django_redis that creates RedisCluster connections.

    RedisCluster manages its own internal per-node connection pools, so we
    override connect() to use RedisCluster.from_url() instead of the default
    Redis(connection_pool=pool) pattern. RedisCluster inherits from Redis and
    implements the same command interface, so django_redis's DefaultClient
    (compression, serialization) works unchanged.
    """

    _cluster_clients: dict[str, RedisCluster] = {}

    def connect(self, url: str) -> RedisCluster:  # type: ignore[override]
        if url not in self._cluster_clients:
            self._cluster_clients[url] = RedisCluster.from_url(url)
        return self._cluster_clients[url]

    def disconnect(self, connection) -> None:  # type: ignore[override]
        connection.close()
