import os
import threading
from collections.abc import Iterable, Mapping
from itertools import batched
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from redis import ConnectionPool, Redis, RedisCluster
from redis.backoff import NoBackoff
from redis.connection import Connection, SSLConnection, parse_url
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)
from redis.retry import Retry

from posthog.redis import get_client
from posthog.security.oob_domains import matched_oob_domain

type QuotaRedisClient = Redis | RedisCluster

QUOTA_WRITE_BATCH_SIZE = 5_000
QUOTA_WRITE_BUDGET_SECONDS = 30.0

_clients: dict[tuple[str, bool, bool, bool], QuotaRedisClient] = {}
_initialization_locks: dict[tuple[str, bool, bool, bool], threading.Lock] = {}
_lock = threading.Lock()


class _QuotaConnectionPool(ConnectionPool):
    def __init__(self, **connection_kwargs: Any) -> None:
        if matched_oob_domain(connection_kwargs.get("host", "localhost")):
            raise RedisConnectionError("Quota Redis host is not permitted")
        connection_class = connection_kwargs.get("connection_class", Connection)
        if issubclass(connection_class, SSLConnection):
            # redis-py cluster filtering drops ssl_check_hostname before it reaches node pools.
            connection_kwargs.update(ssl_check_hostname=True, ssl_cert_reqs="required")
        super().__init__(**connection_kwargs)


def _close_client(client: QuotaRedisClient) -> None:
    if isinstance(client, RedisCluster):
        nodes = [*client.get_nodes(), *client.nodes_manager.startup_nodes.values()]
        pools = {node.redis_connection.connection_pool for node in nodes if node.redis_connection is not None}
    else:
        pools = {client.connection_pool}
    client.close()
    for pool in pools:
        pool.disconnect()


def clear_quota_redis_clients() -> None:
    with _lock:
        for client in _clients.values():
            _close_client(client)
        _clients.clear()
        _initialization_locks.clear()


def _reset_after_fork() -> None:
    global _lock
    _lock = threading.Lock()
    # Cluster clients have callback cycles: their destructors can run after this hook returns.
    for client in _clients.values():
        if isinstance(client, RedisCluster):
            client._lock = threading.Lock()  # type: ignore[attr-defined] # The cluster lock is absent from redis-py's stubs.
            nodes = [*client.get_nodes(), *client.nodes_manager.startup_nodes.values()]
            pools = [node.redis_connection.connection_pool for node in nodes if node.redis_connection is not None]
        else:
            pools = [client.connection_pool]
        for pool in pools:
            pool._lock = threading.Lock()
            pool._fork_lock = threading.Lock()
            pool.reset()
    _clients.clear()
    _initialization_locks.clear()


os.register_at_fork(after_in_child=_reset_after_fork)


def _build_client(url: str, *, cluster: bool, maintenance: bool) -> QuotaRedisClient:
    if settings.TEST:
        return get_client(url)

    options = parse_url(url)
    options.update(
        socket_connect_timeout=0.5,
        socket_timeout=5.0 if maintenance else 0.25,
        max_connections=8 if maintenance else 64,
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
        socket_keepalive=True,
    )
    if not cluster:
        return Redis(connection_pool=_QuotaConnectionPool(**options))

    if options.pop("db", 0) != 0 or "path" in options:
        raise ImproperlyConfigured("Quota Redis clusters require TCP connections to database zero")
    return RedisCluster(
        # URL mode uses our pool for discovery and every later node, including redirects.
        # Parse options once so URL query parameters cannot override the enforced budgets.
        url=urlsplit(url)._replace(query="").geturl(),
        connection_pool_class=_QuotaConnectionPool,
        **options,
        dynamic_startup_nodes=False,
        cluster_error_retry_attempts=0,
        reinitialize_steps=1,
    )


def _cached_client(key: tuple[str, bool, bool, bool]) -> QuotaRedisClient | None:
    if client := _clients.get(key):
        # redis-py can remove the only discovery seed after a connection failure or pool exhaustion.
        if isinstance(client, RedisCluster) and not client.nodes_manager.startup_nodes:
            return None
        return client
    return None


def _get_client(url: str, *, cluster: bool, maintenance: bool) -> QuotaRedisClient:
    key = (url, cluster, maintenance, settings.TEST)
    if client := _cached_client(key):
        return client
    with _lock:
        initialization_lock = _initialization_locks.setdefault(key, threading.Lock())
    # Discovery for a secondary store must not hold up the authoritative store's initialization.
    if not initialization_lock.acquire(timeout=0.25):
        raise RedisConnectionError("Quota Redis client initialization is busy")
    try:
        if client := _cached_client(key):
            return client
        if previous := _clients.pop(key, None):
            _close_client(previous)
        client = _build_client(url, cluster=cluster, maintenance=maintenance)
        _clients[key] = client
        return client
    finally:
        initialization_lock.release()


def get_secondary_quota_redis_client(*, maintenance: bool = False) -> QuotaRedisClient | None:
    if not settings.QUOTA_LIMITING_REDIS_URL:
        return None
    return _get_client(
        settings.QUOTA_LIMITING_REDIS_URL,
        cluster=settings.QUOTA_LIMITING_REDIS_CLUSTER_ENABLED,
        maintenance=maintenance,
    )


def _check_quota_write_budget(deadline: float) -> None:
    if monotonic() >= deadline:
        raise RedisTimeoutError("Quota Redis write budget exceeded")


def reconcile_quota_set(
    client: QuotaRedisClient,
    key: str,
    snapshot_tokens: Iterable[str],
    tokens: Mapping[str, int],
    now: float,
) -> None:
    deadline = monotonic() + QUOTA_WRITE_BUDGET_SECONDS
    _check_quota_write_budget(deadline)
    client.zremrangebyscore(key, "-inf", now)
    stale_tokens = (token for token in snapshot_tokens if token not in tokens)
    for stale_batch in batched(stale_tokens, QUOTA_WRITE_BATCH_SIZE, strict=False):
        _check_quota_write_budget(deadline)
        client.zrem(key, *stale_batch)
    for token_batch in batched(tokens.items(), QUOTA_WRITE_BATCH_SIZE, strict=False):
        _check_quota_write_budget(deadline)
        client.zadd(key, dict(token_batch))
