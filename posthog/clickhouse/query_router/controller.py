import os
import math
import time
import socket
import secrets
from collections.abc import Callable
from enum import StrEnum

from django.conf import settings

import structlog
from prometheus_client import Counter, Gauge

from posthog import redis
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import Pool, PoolBounds, QueryClass, RouterMode
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

# The limit drops by a factor and grows by a fixed step, so it backs off fast when nodes saturate and
# gives capacity back slowly. Between the two thresholds the limit holds, which keeps it from
# oscillating around a single threshold.
HIGH_LOAD_THRESHOLD = 0.5
LOW_LOAD_THRESHOLD = 0.25
LIMIT_DECREASE_FACTOR = 0.85
LIMIT_INCREASE_FRACTION_OF_CEILING = 0.03

TICK_INTERVAL_SECONDS = 1.0
LEADER_LEASE_SECONDS = 5

# While the load read fails, the last limit stays in force this long. After that the controller stops
# writing it, the key expires, and admission falls back to the ceiling instead of a limit that no
# longer follows the nodes.
FAILED_READ_HOLD_SECONDS = 10

# The controller runs in Celery prefork workers and leadership moves between processes. A process
# that does not lead sets its gauges to 0, and livemax exports the highest value among live
# processes, so the leader's value is the one exported.
LIMIT_GAUGE = Gauge(
    "posthog_query_router_limit",
    "Admission limit the controller wrote for a pool. 0 means no controller limit is in force and admission uses the ceiling.",
    ["pool"],
    multiprocess_mode="livemax",
)
LOAD_GAUGE = Gauge(
    "posthog_query_router_load",
    "CPU wait over CPU busy time on the hottest node of a pool.",
    ["pool"],
    multiprocess_mode="livemax",
)
RUNNING_GAUGE = Gauge(
    "posthog_query_router_running",
    "Queries holding an admission slot.",
    ["pool", "query_class"],
    multiprocess_mode="livemax",
)
WAITING_GAUGE = Gauge(
    "posthog_query_router_waiting",
    "Queries waiting for an admission slot.",
    ["pool"],
    multiprocess_mode="livemax",
)
CONTROLLER_TICKS_COUNTER = Counter(
    "posthog_query_router_controller_ticks", "Query router controller ticks by result.", ["result"]
)

LOAD_QUERY = """
SELECT host, cluster_type,
       maxIf(value, name = 'OSCPUWaitMicroseconds') AS cpu_wait_us,
       maxIf(value, name = 'OSCPUVirtualTimeMicroseconds') AS cpu_busy_us,
       maxIf(value, name = 'OSCPUOverload') AS overload
FROM (
    SELECT hostName() AS host, getMacro('hostClusterType') AS cluster_type, event AS name, toFloat64(value) AS value
    FROM clusterAllReplicas(%(cluster)s, system.events)
    WHERE event IN ('OSCPUWaitMicroseconds', 'OSCPUVirtualTimeMicroseconds')
    UNION ALL
    SELECT hostName(), getMacro('hostClusterType'), metric, toFloat64(value)
    FROM clusterAllReplicas(%(cluster)s, system.asynchronous_metrics)
    WHERE metric = 'OSCPUOverload'
)
GROUP BY host, cluster_type
"""

# Only the owner may extend the lease, so a controller that lost it during a pause cannot take it back
# from the controller that replaced it.
_REFRESH_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_POOL_BY_CLUSTER_TYPE: dict[str, Pool] = {pool.value: pool for pool in Pool}


@frozen
class NodeCounters:
    host: str
    # The node's hostClusterType macro. Values other than a Pool value belong to clusters the router
    # does not gate.
    cluster_type: str
    cpu_wait_us: float
    cpu_busy_us: float
    overload: float


def fetch_node_counters() -> list[NodeCounters]:
    with tags_context(product=Product.INTERNAL, feature=Feature.QUERY_ROUTER):
        rows = sync_execute(
            LOAD_QUERY,
            {"cluster": settings.CLICKHOUSE_CLUSTER},
            # A node that does not answer is left out of the read instead of failing it, so one
            # unreachable node does not stop the controller.
            settings={"max_execution_time": 2, "skip_unavailable_shards": 1},
            workload=Workload.ONLINE,
            readonly=True,
            # The default user has a small concurrency limit on the online nodes, which other callers
            # can fill. The operations user keeps the poll working when they do.
            ch_user=ClickHouseUser.OPS,
        )
    return [
        NodeCounters(
            host=host,
            cluster_type=cluster_type,
            cpu_wait_us=cpu_wait_us,
            cpu_busy_us=cpu_busy_us,
            overload=overload,
        )
        for host, cluster_type, cpu_wait_us, cpu_busy_us, overload in rows
    ]


def _node_load(*, current: NodeCounters, previous: NodeCounters | None) -> float:
    # The counters are cumulative since the server started, so only the change between two polls
    # describes the time since the last poll. Without a usable change, OSCPUOverload is the node's own estimate.
    if previous is None:
        return current.overload
    wait_delta = current.cpu_wait_us - previous.cpu_wait_us
    busy_delta = current.cpu_busy_us - previous.cpu_busy_us
    if wait_delta < 0 or busy_delta <= 0:
        return current.overload
    return wait_delta / busy_delta


class LoadReader:
    def __init__(self, fetch: Callable[[], list[NodeCounters]] = fetch_node_counters) -> None:
        self._fetch = fetch
        self._previous_by_host: dict[str, NodeCounters] = {}

    def read(self) -> dict[Pool, float]:
        nodes = self._fetch()
        loads: dict[Pool, float] = {}
        for node in nodes:
            pool = _POOL_BY_CLUSTER_TYPE.get(node.cluster_type)
            if pool is None:
                continue
            load = _node_load(current=node, previous=self._previous_by_host.get(node.host))
            # A distributed query waits for every shard it reads, so the hottest node sets the pool's load.
            loads[pool] = max(load, loads.get(pool, load))
        self._previous_by_host = {node.host: node for node in nodes}
        return loads


def next_limit(*, current: int, load: float, bounds: PoolBounds) -> int:
    if load >= HIGH_LOAD_THRESHOLD:
        proposed = math.floor(current * LIMIT_DECREASE_FACTOR)
    elif load <= LOW_LOAD_THRESHOLD:
        proposed = current + max(1, round(bounds.ceiling * LIMIT_INCREASE_FRACTION_OF_CEILING))
    else:
        proposed = current
    return min(bounds.ceiling, max(bounds.floor, proposed))


class TickResult(StrEnum):
    OK = "ok"
    OFF = "off"
    NOT_LEADER = "not_leader"
    LOAD_READ_FAILED = "load_read_failed"


@frozen
class _PoolLimit:
    value: int
    read_at: float


class LimitController:
    def __init__(self, *, load_reader: LoadReader, get_time: Callable[[], float] = time.time) -> None:
        self._load_reader = load_reader
        self._get_time = get_time
        self._redis = redis.get_client()
        self._owner_id = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
        self._limits: dict[Pool, _PoolLimit] = {}
        self._nonzero_gauges: set[Gauge] = set()
        self._holds_lease = False

    def _hold_lease(self) -> bool:
        refreshed = self._redis.eval(
            _REFRESH_LEASE_SCRIPT, 1, config.CONTROLLER_LEADER_KEY, self._owner_id, str(LEADER_LEASE_SECONDS)
        )
        if refreshed:
            return True
        acquired = self._redis.set(config.CONTROLLER_LEADER_KEY, self._owner_id, nx=True, ex=LEADER_LEASE_SECONDS)
        return bool(acquired)

    def _set_gauge(self, gauge: Gauge, value: float) -> None:
        gauge.set(value)
        self._nonzero_gauges.add(gauge)

    def _zero_gauge(self, gauge: Gauge) -> None:
        gauge.set(0)
        self._nonzero_gauges.discard(gauge)

    def _reset(self) -> None:
        # A process that does not lead exports 0 so the leader's values win, and its next term as
        # leader resumes from the stored limit rather than from one computed before another
        # controller took over.
        for gauge in self._nonzero_gauges:
            gauge.set(0)
        self._nonzero_gauges.clear()
        self._limits.clear()

    def _starting_limit(self, pool: Pool, bounds: PoolBounds) -> int:
        stored = self._redis.get(config.limit_key(pool))
        return int(stored) if stored is not None else bounds.ceiling

    def _write_limit(self, pool: Pool, load: float | None, now: float) -> None:
        limit = self._limits.get(pool)
        if load is not None:
            bounds = config.get_pool_bounds(pool)
            current = limit.value if limit is not None else self._starting_limit(pool, bounds)
            limit = _PoolLimit(value=next_limit(current=current, load=load, bounds=bounds), read_at=now)
            self._limits[pool] = limit
            self._set_gauge(LOAD_GAUGE.labels(pool=pool.value), load)
        elif limit is None:
            return
        elif now - limit.read_at > FAILED_READ_HOLD_SECONDS:
            del self._limits[pool]
            self._zero_gauge(LIMIT_GAUGE.labels(pool=pool.value))
            self._zero_gauge(LOAD_GAUGE.labels(pool=pool.value))
            return
        self._redis.set(config.limit_key(pool), limit.value, ex=config.LIMIT_TTL_SECONDS)
        self._set_gauge(LIMIT_GAUGE.labels(pool=pool.value), limit.value)

    def _record_slot_gauges(self, pool: Pool, now: float) -> None:
        now_ms = int(now * 1000)
        for query_class in QueryClass:
            key = config.running_key(pool, query_class)
            self._redis.zremrangebyscore(key, "-inf", now_ms)
            running = self._redis.zcard(key)
            self._set_gauge(RUNNING_GAUGE.labels(pool=pool.value, query_class=query_class.name.lower()), running)
        waiting = self._redis.zcard(config.waiting_key(pool))
        self._set_gauge(WAITING_GAUGE.labels(pool=pool.value), waiting)

    def stand_down(self) -> None:
        self._reset()
        if not self._holds_lease:
            return
        # Releasing the lease lets a standby take over on its next tick instead of after the lease expires.
        self._redis.eval(_RELEASE_LEASE_SCRIPT, 1, config.CONTROLLER_LEADER_KEY, self._owner_id)
        self._holds_lease = False

    def tick(self) -> TickResult:
        if config.get_global_mode() == RouterMode.OFF:
            self.stand_down()
            CONTROLLER_TICKS_COUNTER.labels(result=TickResult.OFF).inc()
            return TickResult.OFF
        self._holds_lease = self._hold_lease()
        if not self._holds_lease:
            self._reset()
            CONTROLLER_TICKS_COUNTER.labels(result=TickResult.NOT_LEADER).inc()
            return TickResult.NOT_LEADER
        now = self._get_time()
        try:
            loads = self._load_reader.read()
            result = TickResult.OK
        except Exception:
            logger.warning("query_router_load_read_failed", exc_info=True)
            loads = {}
            result = TickResult.LOAD_READ_FAILED
        for pool in Pool:
            self._write_limit(pool, loads.get(pool), now)
            self._record_slot_gauges(pool, now)
        CONTROLLER_TICKS_COUNTER.labels(result=result).inc()
        return result


class ControllerLoop:
    def __init__(
        self,
        controller: LimitController,
        *,
        get_time: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._controller = controller
        self._get_time = get_time
        self._sleep = sleep
        self._stop_requested = False

    def run(self, *, max_seconds: float | None = None) -> None:
        deadline = None if max_seconds is None else self._get_time() + max_seconds
        try:
            while not self._stop_requested:
                started = self._get_time()
                if deadline is not None and started >= deadline:
                    return
                try:
                    result = self._controller.tick()
                except Exception:
                    # A failed tick must not end the run, because this run recovers on its next tick
                    # while the next scheduled run may still be most of a minute away.
                    logger.exception("query_router_controller_tick_failed")
                else:
                    # With the router off a run ends at once instead of holding a worker. The next
                    # scheduled run starts the loop again after the router is turned on.
                    if result == TickResult.OFF:
                        return
                elapsed = self._get_time() - started
                self._sleep(max(0.0, TICK_INTERVAL_SECONDS - elapsed))
        finally:
            self._controller.stand_down()

    def stop(self) -> None:
        self._stop_requested = True
