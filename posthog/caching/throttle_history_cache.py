from typing import Any

from django_redis.pool import ConnectionFactory
from redis import ConnectionPool


class ThrottleHistoryConnectionFactory(ConnectionFactory):
    _pools: dict[str, ConnectionPool] = {}


def throttle_history_cache(default: dict[str, Any]) -> dict[str, Any]:
    location = default["LOCATION"]
    return {
        **default,
        "LOCATION": location[0] if isinstance(location, list | tuple) else location,
        "OPTIONS": {
            **default.get("OPTIONS", {}),
            "CONNECTION_FACTORY": f"{__name__}.{ThrottleHistoryConnectionFactory.__name__}",
            "SOCKET_CONNECT_TIMEOUT": 0.2,
            "SOCKET_TIMEOUT": 0.2,
        },
    }
