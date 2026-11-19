from django_redis.pool import ConnectionFactory
from redis import ConnectionPool


class ThrottleHistoryConnectionFactory(ConnectionFactory):
    _pools: dict[str, ConnectionPool] = {}
