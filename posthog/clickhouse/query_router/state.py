from collections.abc import Mapping

from prometheus_client import Gauge
from redis import Redis

from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import STALE_WAITER_MS, Pool, QueryClass
from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry

# The controller loop exports between two ticks. A push that hangs must end well before the leader
# lease and the limit key expire.
_PUSH_TIMEOUT_SECONDS = 2


@frozen
class PoolState:
    # None when the controller has not written the key or the key expired.
    limit: int | None
    load: float | None
    # Epoch seconds of the last limit the controller computed from a load read. None while the router
    # is off, and until the first load read after it is turned on.
    limit_updated_at: float | None
    running: Mapping[QueryClass, int]
    waiting: int


@frozen
class RouterState:
    pools: Mapping[Pool, PoolState]


def _read_pool_state(redis_client: Redis, pool: Pool, *, now_ms: int) -> PoolState:
    limit = redis_client.get(config.limit_key(pool))
    load = redis_client.get(config.load_key(pool))
    limit_updated_at = redis_client.get(config.limit_updated_key(pool))
    # Admission removes expired slots and stale waiters only when a query tries to enter, so a quiet
    # pool keeps them in Redis. The counts skip them by score instead.
    running = {
        query_class: int(redis_client.zcount(config.running_key(pool, query_class), f"({now_ms}", "+inf"))
        for query_class in QueryClass
    }
    waiting = int(redis_client.zcount(config.waiting_seen_key(pool), f"({now_ms - STALE_WAITER_MS}", "+inf"))
    return PoolState(
        limit=None if limit is None else int(limit),
        load=None if load is None else float(load),
        limit_updated_at=None if limit_updated_at is None else float(limit_updated_at),
        running=running,
        waiting=waiting,
    )


def read_router_state(redis_client: Redis, *, now: float) -> RouterState:
    now_ms = int(now * 1000)
    return RouterState(pools={pool: _read_pool_state(redis_client, pool, now_ms=now_ms) for pool in Pool})


def push_router_state(state: RouterState) -> None:
    with pushed_metrics_registry("query_router", timeout_seconds=_PUSH_TIMEOUT_SECONDS) as registry:
        limit_gauge = Gauge(
            "posthog_query_router_limit",
            "Admission limit the controller wrote for a pool. A pool without a series has no controller limit in force, and admission uses the ceiling.",
            ["pool"],
            registry=registry,
        )
        load_gauge = Gauge(
            "posthog_query_router_load",
            "CPU wait over CPU busy time on the hottest node of a pool.",
            ["pool"],
            registry=registry,
        )
        limit_updated_gauge = Gauge(
            "posthog_query_router_limit_updated_timestamp_seconds",
            "Time of the last limit the controller computed from a load read, in epoch seconds.",
            ["pool"],
            registry=registry,
        )
        running_gauge = Gauge(
            "posthog_query_router_running",
            "Queries holding an admission slot.",
            ["pool", "query_class"],
            registry=registry,
        )
        waiting_gauge = Gauge(
            "posthog_query_router_waiting",
            "Queries waiting for an admission slot.",
            ["pool"],
            registry=registry,
        )
        for pool, pool_state in state.pools.items():
            if pool_state.limit is not None:
                limit_gauge.labels(pool=pool.value).set(pool_state.limit)
            if pool_state.load is not None:
                load_gauge.labels(pool=pool.value).set(pool_state.load)
            if pool_state.limit_updated_at is not None:
                limit_updated_gauge.labels(pool=pool.value).set(pool_state.limit_updated_at)
            for query_class, running in pool_state.running.items():
                running_gauge.labels(pool=pool.value, query_class=query_class.name.lower()).set(running)
            waiting_gauge.labels(pool=pool.value).set(pool_state.waiting)
