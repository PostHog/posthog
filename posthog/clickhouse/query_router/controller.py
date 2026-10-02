import os
import math
import time
import socket
import secrets
from collections.abc import Callable, Mapping
from enum import StrEnum

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog import redis
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import Pool, PoolBounds, RouterMode
from posthog.clickhouse.query_router.state import push_router_state, read_router_state
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

# A read that misses a node can miss the hottest node, so the limit may not rise on it. A node that
# drops out because it is overloaded comes back within minutes. A node taken out for maintenance can
# stay out for hours, and without a bound the limit could then only fall. So the limit may rise again
# once no read has reached every node for this long. Redis keeps the time of the last complete read,
# because leadership moves to another process when the leader stops or loses its lease.
PARTIAL_SAMPLE_HOLD_SECONDS = 300

# Every controller exports the same state from Redis, so a controller exports whether it leads or not.
STATE_EXPORT_INTERVAL_SECONDS = 15

CONTROLLER_TICKS_COUNTER = Counter(
    "posthog_query_router_controller_ticks", "Query router controller ticks by result.", ["result"]
)

LOAD_QUERY = """
SELECT host, cluster_type,
       maxIf(value, name = 'OSCPUWaitMicroseconds') AS cpu_wait_us,
       maxIf(value, name = 'OSCPUVirtualTimeMicroseconds') AS cpu_busy_us,
       maxIf(value, name = 'OSCPUOverload') AS overload,
       (SELECT uniqExact(host_name) FROM system.clusters WHERE cluster = %(cluster)s) AS cluster_nodes
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


@frozen
class NodeSample:
    nodes: list[NodeCounters]
    # Nodes the cluster has, including the nodes that did not answer.
    cluster_nodes: int


def fetch_node_counters() -> NodeSample:
    with tags_context(product=Product.INTERNAL, feature=Feature.QUERY_ROUTER):
        rows = sync_execute(
            LOAD_QUERY,
            {"cluster": settings.CLICKHOUSE_CLUSTER},
            # A node that does not answer is left out of the read instead of failing it, so one
            # unreachable node does not stop the controller. The read then has fewer hosts than
            # cluster_nodes, which marks it partial.
            settings={"max_execution_time": 2, "skip_unavailable_shards": 1},
            workload=Workload.ONLINE,
            readonly=True,
            # Other callers can fill the default user's concurrency limit. The operations user keeps
            # the poll working when they do.
            ch_user=ClickHouseUser.OPS,
        )
    if not rows:
        raise RuntimeError("no ClickHouse node answered the load query")
    nodes = [
        NodeCounters(
            host=host,
            cluster_type=cluster_type,
            cpu_wait_us=cpu_wait_us,
            cpu_busy_us=cpu_busy_us,
            overload=overload,
        )
        for host, cluster_type, cpu_wait_us, cpu_busy_us, overload, _cluster_nodes in rows
    ]
    # Every row carries the same cluster size.
    cluster_nodes = rows[0][5]
    return NodeSample(nodes=nodes, cluster_nodes=cluster_nodes)


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


@frozen
class PoolLoads:
    loads: Mapping[Pool, float]
    # False when any node of the cluster did not answer, so a missing node holds increases in every
    # pool. A node that does not answer cannot report which pool it belongs to.
    complete: bool


class LoadReader:
    def __init__(self, fetch: Callable[[], NodeSample] = fetch_node_counters) -> None:
        self._fetch = fetch
        self._previous_by_host: dict[str, NodeCounters] = {}

    def read(self) -> PoolLoads:
        sample = self._fetch()
        loads: dict[Pool, float] = {}
        for node in sample.nodes:
            pool = _POOL_BY_CLUSTER_TYPE.get(node.cluster_type)
            if pool is None:
                continue
            load = _node_load(current=node, previous=self._previous_by_host.get(node.host))
            # A distributed query waits for every shard it reads, so the hottest node sets the pool's load.
            loads[pool] = max(load, loads.get(pool, load))
        self._previous_by_host = {node.host: node for node in sample.nodes}
        hosts = {node.host for node in sample.nodes}
        return PoolLoads(loads=loads, complete=len(hosts) >= sample.cluster_nodes)


def next_limit(*, current: int, load: float, bounds: PoolBounds, may_increase: bool) -> int:
    if load >= HIGH_LOAD_THRESHOLD:
        proposed = math.floor(current * LIMIT_DECREASE_FACTOR)
    elif load <= LOW_LOAD_THRESHOLD and may_increase:
        proposed = current + max(1, round(bounds.ceiling * LIMIT_INCREASE_FRACTION_OF_CEILING))
    else:
        proposed = current
    return min(bounds.ceiling, max(bounds.floor, proposed))


class TickResult(StrEnum):
    OK = "ok"
    OFF = "off"
    NOT_LEADER = "not_leader"
    LOAD_READ_FAILED = "load_read_failed"
    PARTIAL_SAMPLE = "partial_sample"


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
        self._holds_lease = False

    def _hold_lease(self) -> bool:
        refreshed = self._redis.eval(
            _REFRESH_LEASE_SCRIPT, 1, config.CONTROLLER_LEADER_KEY, self._owner_id, str(LEADER_LEASE_SECONDS)
        )
        if refreshed:
            return True
        acquired = self._redis.set(config.CONTROLLER_LEADER_KEY, self._owner_id, nx=True, ex=LEADER_LEASE_SECONDS)
        return bool(acquired)

    def _reset(self) -> None:
        # The next term as leader resumes from the stored limit rather than from one computed before
        # another controller took over.
        self._limits.clear()

    def _starting_limit(self, pool: Pool, bounds: PoolBounds) -> int:
        stored = self._redis.get(config.limit_key(pool))
        return int(stored) if stored is not None else bounds.ceiling

    def _partial_sample_may_increase(self, now: float) -> bool:
        hold_started = self._redis.get(config.CONTROLLER_LAST_COMPLETE_SAMPLE_KEY)
        if hold_started is None:
            # No read has reached every node yet, so the hold starts with this read.
            self._redis.set(config.CONTROLLER_LAST_COMPLETE_SAMPLE_KEY, now, nx=True)
            return False
        return now - float(hold_started) > PARTIAL_SAMPLE_HOLD_SECONDS

    def _write_limit(self, pool: Pool, load: float | None, now: float, *, may_increase: bool) -> None:
        limit = self._limits.get(pool)
        if load is not None:
            bounds = config.get_pool_bounds(pool)
            current = limit.value if limit is not None else self._starting_limit(pool, bounds)
            limit = _PoolLimit(
                value=next_limit(current=current, load=load, bounds=bounds, may_increase=may_increase), read_at=now
            )
            self._limits[pool] = limit
            self._redis.set(config.load_key(pool), load, ex=config.LIMIT_TTL_SECONDS)
            # This time has no expiry, so it stays in the exported state after the limit lapses. An alert
            # on its age then fires when the load read keeps failing, although the controller still runs
            # and still exports.
            self._redis.set(config.limit_updated_key(pool), now)
        elif limit is None:
            return
        elif now - limit.read_at > FAILED_READ_HOLD_SECONDS:
            del self._limits[pool]
            return
        self._redis.set(config.limit_key(pool), limit.value, ex=config.LIMIT_TTL_SECONDS)

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
            # With the router off no limit is due, so the exported state must not carry a time that ages.
            for pool in Pool:
                self._redis.delete(config.limit_updated_key(pool))
            CONTROLLER_TICKS_COUNTER.labels(result=TickResult.OFF).inc()
            return TickResult.OFF
        self._holds_lease = self._hold_lease()
        if not self._holds_lease:
            self._reset()
            CONTROLLER_TICKS_COUNTER.labels(result=TickResult.NOT_LEADER).inc()
            return TickResult.NOT_LEADER
        now = self._get_time()
        sample: PoolLoads | None
        try:
            sample = self._load_reader.read()
        except Exception:
            logger.warning("query_router_load_read_failed", exc_info=True)
            sample = None
        # A slow load read can outlast the lease. A controller that lost it in the meantime must not
        # overwrite the limit of the controller that replaced it.
        self._holds_lease = self._hold_lease()
        if not self._holds_lease:
            self._reset()
            CONTROLLER_TICKS_COUNTER.labels(result=TickResult.NOT_LEADER).inc()
            return TickResult.NOT_LEADER
        loads: Mapping[Pool, float]
        if sample is None:
            loads = {}
            may_increase = False
            result = TickResult.LOAD_READ_FAILED
        elif sample.complete:
            self._redis.set(config.CONTROLLER_LAST_COMPLETE_SAMPLE_KEY, now)
            loads = sample.loads
            may_increase = True
            result = TickResult.OK
        else:
            loads = sample.loads
            may_increase = self._partial_sample_may_increase(now)
            result = TickResult.PARTIAL_SAMPLE
        for pool in Pool:
            self._write_limit(pool, loads.get(pool), now, may_increase=may_increase)
        CONTROLLER_TICKS_COUNTER.labels(result=result).inc()
        return result


def _export_router_state() -> None:
    state = read_router_state(redis.get_client(), now=time.time())
    push_router_state(state)


class ControllerLoop:
    def __init__(
        self,
        controller: LimitController,
        *,
        heartbeat: Callable[[], None],
        get_time: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        export_state: Callable[[], None] = _export_router_state,
    ) -> None:
        self._controller = controller
        self._heartbeat = heartbeat
        self._get_time = get_time
        self._sleep = sleep
        self._export_state = export_state
        self._stop_requested = False

    def _export(self) -> None:
        try:
            self._export_state()
        except Exception:
            # A failed export must not end the loop, because the loop keeps the limit current and the
            # next export usually succeeds.
            logger.exception("query_router_state_export_failed")

    def run(self) -> None:
        next_export = self._get_time() + STATE_EXPORT_INTERVAL_SECONDS
        try:
            while not self._stop_requested:
                started = self._get_time()
                self._heartbeat()
                try:
                    self._controller.tick()
                except Exception:
                    # A failed tick must not end the loop, because the next tick usually recovers and a
                    # restarted process needs much longer before its first tick.
                    logger.exception("query_router_controller_tick_failed")
                if started >= next_export:
                    self._export()
                    next_export = started + STATE_EXPORT_INTERVAL_SECONDS
                elapsed = self._get_time() - started
                self._sleep(max(0.0, TICK_INTERVAL_SECONDS - elapsed))
        finally:
            self._controller.stand_down()

    def stop(self) -> None:
        self._stop_requested = True
