import itertools

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog import redis
from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import Pool, PoolBounds, QueryClass, RouterMode
from posthog.clickhouse.query_router.controller import (
    PARTIAL_SAMPLE_HOLD_SECONDS,
    ControllerLoop,
    LimitController,
    LoadReader,
    NodeCounters,
    NodeSample,
    PoolLoads,
    TickResult,
    next_limit,
)
from posthog.clickhouse.query_router.state import PoolState, read_router_state

BOUNDS = PoolBounds(floor=80, ceiling=400)


def _node(host: str, cluster_type: str, *, wait: float = 0.0, busy: float = 0.0, overload: float = 0.0) -> NodeCounters:
    return NodeCounters(host=host, cluster_type=cluster_type, cpu_wait_us=wait, cpu_busy_us=busy, overload=overload)


def _sample(*nodes: NodeCounters, cluster_nodes: int | None = None) -> NodeSample:
    return NodeSample(nodes=list(nodes), cluster_nodes=len(nodes) if cluster_nodes is None else cluster_nodes)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class _FakeFetch:
    def __init__(self, sample: NodeSample) -> None:
        self.sample = sample
        self.error: Exception | None = None

    def __call__(self) -> NodeSample:
        if self.error is not None:
            raise self.error
        return self.sample


class TestNextLimit(SimpleTestCase):
    @parameterized.expand(
        [
            ("decrease_at_high_load", 400, 0.5, True, BOUNDS, 340),
            ("decrease_rounds_down", 101, 1.2, True, BOUNDS, 85),
            ("decrease_stops_at_floor", 90, 0.9, True, BOUNDS, 80),
            ("increase_at_low_load", 200, 0.25, True, BOUNDS, 212),
            ("increase_stops_at_ceiling", 395, 0.0, True, BOUNDS, 400),
            ("increase_step_is_at_least_one", 5, 0.0, True, PoolBounds(floor=1, ceiling=10), 6),
            ("hold_at_low_load_when_increases_are_held", 200, 0.0, False, BOUNDS, 200),
            ("hold_between_thresholds", 200, 0.3, True, BOUNDS, 200),
            ("hold_clamps_to_a_lowered_ceiling", 400, 0.3, True, PoolBounds(floor=80, ceiling=300), 300),
        ]
    )
    def test_next_limit(
        self, _name: str, current: int, load: float, may_increase: bool, bounds: PoolBounds, expected: int
    ) -> None:
        assert next_limit(current=current, load=load, bounds=bounds, may_increase=may_increase) == expected


class TestLoadReader(SimpleTestCase):
    def test_node_load_is_wait_over_busy_delta_with_overload_when_there_is_no_usable_delta(self) -> None:
        polls = iter(
            [
                _sample(_node("ch1", "offline", wait=1_000, busy=10_000, overload=0.7)),
                _sample(_node("ch1", "offline", wait=3_000, busy=14_000, overload=0.9)),
                _sample(_node("ch1", "offline", wait=100, busy=500, overload=0.2)),
                _sample(_node("ch1", "offline", wait=200, busy=500, overload=0.3)),
            ]
        )
        reader = LoadReader(fetch=lambda: next(polls))

        loads = [reader.read().loads[Pool.OFFLINE] for _ in range(4)]

        assert loads == [0.7, 0.5, 0.2, 0.3]

    @parameterized.expand(
        [
            ("every_node_answered", 5, True),
            ("a_node_did_not_answer", 6, False),
        ]
    )
    def test_hottest_node_sets_the_pool_load_and_a_missing_node_makes_the_read_partial(
        self, _name: str, cluster_nodes: int, complete: bool
    ) -> None:
        reader = LoadReader(
            fetch=lambda: _sample(
                _node("off1", "offline", overload=0.1),
                _node("off2", "offline", overload=0.9),
                _node("on1", "online", overload=0.2),
                _node("on2", "online", overload=0.05),
                _node("logs1", "logs", overload=5.0),
                cluster_nodes=cluster_nodes,
            )
        )

        assert reader.read() == PoolLoads(loads={Pool.OFFLINE: 0.9, Pool.ONLINE: 0.2}, complete=complete)


class TestLimitController(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(config, "get_global_mode", return_value=RouterMode.OBSERVE))
        self.enterContext(patch.object(config, "get_pool_bounds", return_value=BOUNDS))
        self.redis = redis.get_client()
        self.clock = _FakeClock()
        self._delete_controller_keys()
        self.addCleanup(self._delete_controller_keys)

    def _delete_controller_keys(self) -> None:
        self.redis.delete(
            config.CONTROLLER_LEADER_KEY,
            config.CONTROLLER_LAST_COMPLETE_SAMPLE_KEY,
            *(config.limit_key(pool) for pool in Pool),
            *(config.load_key(pool) for pool in Pool),
            *(config.waiting_seen_key(pool) for pool in Pool),
            *(config.running_key(pool, query_class) for pool in Pool for query_class in QueryClass),
        )

    def _written_limits(self) -> dict[Pool, int]:
        limits: dict[Pool, int] = {}
        for pool in Pool:
            value = self.redis.get(config.limit_key(pool))
            if value is not None:
                limits[pool] = int(value)
        return limits

    def _controller(self, fetch: _FakeFetch) -> LimitController:
        return LimitController(load_reader=LoadReader(fetch=fetch), get_time=self.clock)

    def test_controller_without_the_lease_writes_nothing(self) -> None:
        fetch = _FakeFetch(_sample(_node("off1", "offline", overload=0.9), _node("on1", "online", overload=0.9)))
        leader = self._controller(fetch)
        follower = self._controller(fetch)

        leader.tick()
        assert self._written_limits() == {Pool.OFFLINE: 340, Pool.ONLINE: 340}
        self.redis.delete(*(config.limit_key(pool) for pool in Pool))
        follower.tick()

        assert self._written_limits() == {}

    def test_controller_that_loses_the_lease_during_the_load_read_writes_nothing(self) -> None:
        def fetch_while_another_controller_takes_over() -> NodeSample:
            self.redis.set(config.CONTROLLER_LEADER_KEY, "another-controller", ex=5)
            return _sample(_node("off1", "offline", overload=0.9), _node("on1", "online", overload=0.9))

        controller = LimitController(
            load_reader=LoadReader(fetch=fetch_while_another_controller_takes_over), get_time=self.clock
        )
        controller.tick()

        assert self._written_limits() == {}

    def test_new_leader_continues_from_the_limit_the_previous_leader_wrote(self) -> None:
        self._controller(
            _FakeFetch(_sample(_node("off1", "offline", overload=0.9), _node("on1", "online", overload=0.9)))
        ).tick()
        self.redis.delete(config.CONTROLLER_LEADER_KEY)

        self._controller(_FakeFetch(_sample(_node("off1", "offline"), _node("on1", "online")))).tick()

        assert self._written_limits() == {Pool.OFFLINE: 352, Pool.ONLINE: 352}

    @parameterized.expand(
        [
            ("after_a_complete_read", 2),
            ("when_no_read_was_ever_complete", 3),
        ]
    )
    def test_missing_node_holds_the_limit_across_leaders_until_the_hold_runs_out(
        self, _name: str, cluster_nodes: int
    ) -> None:
        hot = _node("off1", "offline", overload=0.9)
        cold = _node("off2", "offline")
        complete_at = self.clock.now
        self._controller(_FakeFetch(_sample(hot, cold, cluster_nodes=cluster_nodes))).tick()
        assert self._written_limits() == {Pool.OFFLINE: 340}
        self.redis.delete(config.CONTROLLER_LEADER_KEY)

        controller = self._controller(_FakeFetch(_sample(cold, cluster_nodes=cluster_nodes)))
        results = []
        limits = []
        for seconds_since_complete in (1, PARTIAL_SAMPLE_HOLD_SECONDS, PARTIAL_SAMPLE_HOLD_SECONDS + 1):
            self.clock.now = complete_at + seconds_since_complete
            results.append(controller.tick())
            limits.append(self._written_limits()[Pool.OFFLINE])

        assert results == [TickResult.PARTIAL_SAMPLE] * 3
        assert limits == [340, 340, 352]

    def test_router_state_counts_live_slots_and_recent_waiters_and_reports_a_missing_limit_as_none(self) -> None:
        now_ms = int(self.clock.now * 1000)
        self.redis.zadd(
            config.running_key(Pool.OFFLINE, QueryClass.BACKGROUND),
            {"live": now_ms + 5_000, "expired": now_ms - 5_000},
        )
        self.redis.zadd(
            config.waiting_seen_key(Pool.OFFLINE),
            {"polling": now_ms - 1_000, "gone": now_ms - config.STALE_WAITER_MS - 1_000},
        )

        self._controller(_FakeFetch(_sample(_node("off1", "offline", overload=0.9)))).tick()
        state = read_router_state(self.redis, now=self.clock.now)

        idle = dict.fromkeys(QueryClass, 0)
        assert state.pools == {
            Pool.OFFLINE: PoolState(limit=340, load=0.9, running={**idle, QueryClass.BACKGROUND: 1}, waiting=1),
            Pool.ONLINE: PoolState(limit=None, load=None, running=idle, waiting=0),
        }

    @parameterized.expand(
        [
            ("off_when_the_run_starts", [], 0),
            ("turned_off_while_leading", [RouterMode.OBSERVE], 1),
        ]
    )
    def test_run_ends_and_leaves_no_lease_once_the_router_is_off(
        self, _name: str, modes_before_off: list[RouterMode], expected_sleeps: int
    ) -> None:
        off_ticks_before = REGISTRY.get_sample_value("posthog_query_router_controller_ticks_total", {"result": "off"})
        exports: list[float] = []
        loop = ControllerLoop(
            self._controller(_FakeFetch(_sample(_node("off1", "offline"), _node("on1", "online")))),
            get_time=self.clock,
            sleep=self.clock.sleep,
            export_state=lambda: exports.append(self.clock.now),
        )

        with patch.object(
            config, "get_global_mode", side_effect=itertools.chain(modes_before_off, itertools.repeat(RouterMode.OFF))
        ):
            loop.run(max_seconds=120)

        off_ticks_after = REGISTRY.get_sample_value("posthog_query_router_controller_ticks_total", {"result": "off"})
        assert len(self.clock.slept) == expected_sleeps
        assert self.redis.get(config.CONTROLLER_LEADER_KEY) is None
        assert (off_ticks_after or 0) - (off_ticks_before or 0) == 1
        assert len(exports) == 1

    def test_run_exports_the_state_every_interval_and_when_it_ends(self) -> None:
        started = self.clock.now
        exports: list[float] = []
        loop = ControllerLoop(
            self._controller(_FakeFetch(_sample(_node("off1", "offline"), _node("on1", "online")))),
            get_time=self.clock,
            sleep=self.clock.sleep,
            export_state=lambda: exports.append(self.clock.now - started),
        )

        loop.run(max_seconds=60)

        assert exports == [15, 30, 45, 60]

    def test_stops_rewriting_the_limit_ten_seconds_after_the_last_good_read(self) -> None:
        fetch = _FakeFetch(_sample(_node("off1", "offline", overload=0.9), _node("on1", "online", overload=0.0)))
        controller = self._controller(fetch)
        controller.tick()
        fetch.error = RuntimeError("clickhouse unavailable")

        written = []
        for _ in range(12):
            self.clock.now += 1.0
            self.redis.delete(*(config.limit_key(pool) for pool in Pool))
            controller.tick()
            written.append(self._written_limits())

        assert written == [{Pool.OFFLINE: 340, Pool.ONLINE: 400}] * 10 + [{}] * 2
