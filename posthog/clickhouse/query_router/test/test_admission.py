import queue
import threading
from contextlib import AbstractContextManager, ExitStack

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import fakeredis
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.clickhouse.query_router.admission import (
    _SLOT_RENEW_INTERVAL_SECONDS,
    _SLOT_TTL_SECONDS,
    Admission,
    AdmissionOutcome,
    QueryRouter,
)
from posthog.clickhouse.query_router.config import (
    ARRIVALS_WINDOW_MS,
    DURATION_HISTORY,
    MAX_WAIT_SECONDS,
    STALE_WAITER_MS,
    Pool,
    QueryClass,
    RouterMode,
    arrivals_key,
    durations_key,
    running_key,
    waiting_key,
    waiting_seen_key,
)
from posthog.clickhouse.query_router.test.fakes import FakeClock, router_settings
from posthog.exceptions import ClickHouseAtCapacity
from posthog.redis import get_client

# One held slot fills the pool.
SMALL_LIMIT = 1

# Query durations that make the next query's estimated wait fit half the max wait, or not, at the limits
# these tests use.
FAST_QUERY_SECONDS = 0.5
SLOW_QUERY_SECONDS = 9.0


def _sample_value(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class _ParkedWaiter:
    # Runs admit() on its own thread and stops it at every poll sleep until the test steps it, so a
    # test chooses which of several queued queries polls next.
    def __init__(self, clock: FakeClock, query_class: QueryClass) -> None:
        self._query_class = query_class
        self.sleeps: list[float] = []
        self._events: queue.Queue[str] = queue.Queue()
        self._steps: queue.Queue[None] = queue.Queue()
        self._router = QueryRouter(redis_client=get_client(), get_time=clock.time, sleep=self._park)
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> str:
        self._thread.start()
        return self._events.get(timeout=5)

    def step(self) -> str:
        self._steps.put(None)
        return self._events.get(timeout=5)

    def finish(self) -> None:
        while self.step() not in ("released", "dropped"):
            pass
        self._thread.join(timeout=5)

    def _park(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._events.put("waiting")
        self._steps.get(timeout=5)

    def _run(self) -> None:
        try:
            with self._router.admit(pool=Pool.OFFLINE, query_class=self._query_class):
                self._events.put("admitted")
                self._steps.get(timeout=5)
        except ClickHouseAtCapacity:
            self._events.put("dropped")
            return
        self._events.put("released")


class TestQueryRouterAdmission(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = FakeClock()
        self.redis = get_client()
        self.router = QueryRouter(redis_client=self.redis, get_time=self.clock.time, sleep=self.clock.sleep)
        self.get_settings = self._start_patch(
            "posthog.clickhouse.query_router.config.get_settings", router_settings(limit=SMALL_LIMIT)
        )
        self.addCleanup(self._delete_router_keys)

    def _start_patch(self, target: str, return_value: object) -> MagicMock:
        patcher = patch(target, return_value=return_value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _delete_router_keys(self) -> None:
        for pool in Pool:
            self.redis.delete(
                *(running_key(pool, query_class) for query_class in QueryClass),
                waiting_key(pool),
                waiting_seen_key(pool),
                durations_key(pool),
                arrivals_key(pool),
            )

    def _admit(self, query_class: QueryClass) -> AbstractContextManager[Admission]:
        return self.router.admit(pool=Pool.OFFLINE, query_class=query_class)

    def _hold(self, stack: ExitStack, count: int, query_class: QueryClass = QueryClass.INTERACTIVE) -> None:
        for _ in range(count):
            stack.enter_context(self._admit(query_class))

    def _finish(self, seconds: float = FAST_QUERY_SECONDS) -> None:
        # No class ranks below BACKGROUND, so the arrival counts against no later query.
        with self._admit(QueryClass.BACKGROUND):
            self.clock.now += seconds

    def _running(self, query_class: QueryClass) -> int:
        return self.redis.zcard(running_key(Pool.OFFLINE, query_class))

    def test_every_class_starts_while_the_pool_is_under_the_limit(self) -> None:
        self.get_settings.return_value = router_settings(limit=10)

        with ExitStack() as held:
            self._hold(held, 9)
            with self._admit(QueryClass.BACKGROUND) as admission:
                assert admission.outcome == AdmissionOutcome.ADMITTED

    @parameterized.expand(
        [
            ("higher_class_before_earlier_arrival", QueryClass.BACKGROUND, QueryClass.API, False),
            ("same_class_in_arrival_order", QueryClass.BACKGROUND, QueryClass.BACKGROUND, True),
        ]
    )
    def test_freed_slot_goes_to_the_waiter_ranked_first(
        self, _name: str, early_class: QueryClass, late_class: QueryClass, early_wins: bool
    ) -> None:
        self._finish()
        early = _ParkedWaiter(self.clock, early_class)
        late = _ParkedWaiter(self.clock, late_class)
        with ExitStack() as held:
            self._hold(held, 1)
            assert early.start() == "waiting"
            self.clock.now += 0.1
            assert late.start() == "waiting"

        winner, loser = (early, late) if early_wins else (late, early)
        self.clock.now += 0.1
        assert loser.step() == "waiting"
        self.clock.now += 0.1
        assert winner.step() == "admitted"

        winner.finish()
        loser.finish()

    def test_waiter_polls_less_often_the_further_it_is_from_the_head(self) -> None:
        self.enterContext(patch("posthog.clickhouse.query_router.admission.random.uniform", return_value=1.0))
        self._finish()
        waiters = [_ParkedWaiter(self.clock, QueryClass.BACKGROUND) for _ in range(4)]
        with ExitStack() as held:
            self._hold(held, 1)
            for waiter in waiters:
                assert waiter.start() == "waiting"
                self.clock.now += 0.01

        head, deep = waiters[0], waiters[-1]
        assert head.sleeps[0] <= 0.05
        assert deep.sleeps[0] > head.sleeps[0]

        for waiter in waiters:
            waiter.finish()

    def test_waiter_is_dropped_after_its_max_wait_and_counted_for_its_team(self) -> None:
        drops = ("posthog_query_router_drops_total", {"pool": "offline", "query_class": "background", "team_id": "42"})
        drops_before = _sample_value(*drops)
        self._finish()
        started_at = self.clock.now
        with ExitStack() as held:
            self._hold(held, 1)
            with self.assertRaises(ClickHouseAtCapacity) as dropped:
                with self.router.admit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND, team_id=42):
                    pass

        self.assertAlmostEqual(self.clock.now - started_at, MAX_WAIT_SECONDS, places=3)
        assert 3 <= dropped.exception.wait <= 8
        assert _sample_value(*drops) == drops_before + 1
        assert self.redis.zcard(waiting_key(Pool.OFFLINE)) == 0
        assert self.redis.zcard(waiting_seen_key(Pool.OFFLINE)) == 0

    def test_waiter_that_wakes_after_its_max_wait_is_dropped_even_when_the_pool_has_freed(self) -> None:
        max_wait_seconds = MAX_WAIT_SECONDS
        self._finish()
        with ExitStack() as held:
            self._hold(held, 1)

            def oversleep_while_the_pool_frees(_seconds: float) -> None:
                held.close()
                self.clock.sleep(max_wait_seconds + 1)

            self.router.sleep = oversleep_while_the_pool_frees
            with self.assertRaises(ClickHouseAtCapacity):
                with self._admit(QueryClass.API):
                    pass

        assert self.redis.zcard(waiting_key(Pool.OFFLINE)) == 0
        assert self.redis.zcard(waiting_seen_key(Pool.OFFLINE)) == 0

    def test_waiter_interrupted_in_its_sleep_leaves_the_queue(self) -> None:
        class Interrupted(BaseException):
            pass

        def interrupt(_seconds: float) -> None:
            raise Interrupted

        self.router.sleep = interrupt
        self._finish()
        with ExitStack() as held:
            self._hold(held, 1)
            with self.assertRaises(Interrupted):
                with self._admit(QueryClass.BACKGROUND):
                    pass

            assert self.redis.zcard(waiting_key(Pool.OFFLINE)) == 0
            assert self.redis.zcard(waiting_seen_key(Pool.OFFLINE)) == 0

    @parameterized.expand(
        [
            ("no_query_finished_yet", QueryClass.API, None, 0, True),
            ("fast_queries", QueryClass.API, FAST_QUERY_SECONDS, 0, True),
            ("slow_queries", QueryClass.API, SLOW_QUERY_SECONDS, 0, False),
            ("higher_class_arrivals_take_the_freed_slots", QueryClass.BACKGROUND, 4.0, 0, False),
            ("higher_class_arrivals_older_than_the_window", QueryClass.BACKGROUND, 4.0, ARRIVALS_WINDOW_MS + 1, True),
        ]
    )
    def test_query_queues_only_when_the_pool_frees_a_slot_within_half_its_max_wait(
        self, _name: str, query_class: QueryClass, duration_seconds: float | None, arrivals_age_ms: int, queues: bool
    ) -> None:
        # With a limit of 3 and three API queries running, the next query needs one freed slot. At 4 seconds
        # per query the pool frees 0.75 slots a second, enough for an API query, but the three API arrivals
        # in the window take 0.6 of those from a BACKGROUND query.
        self.get_settings.return_value = router_settings(limit=3)
        if duration_seconds is not None:
            self._finish(duration_seconds)
        with ExitStack() as held:
            self._hold(held, 3, QueryClass.API)
            self.clock.now += arrivals_age_ms / 1000
            started_at = self.clock.now

            def free_the_pool_and_sleep(seconds: float) -> None:
                held.close()
                self.clock.sleep(seconds)

            self.router.sleep = free_the_pool_and_sleep
            if queues:
                with self._admit(query_class) as admission:
                    assert admission.outcome == AdmissionOutcome.ADMITTED_AFTER_WAIT
            else:
                with self.assertRaises(ClickHouseAtCapacity):
                    with self._admit(query_class):
                        pass
                assert self.clock.now == started_at
                assert self.redis.zcard(waiting_key(Pool.OFFLINE)) == 0

    @parameterized.expand(
        [
            ("renewed_by_its_process", True, 2 * 3600, AdmissionOutcome.WOULD_WAIT),
            (
                "left_by_a_dead_process",
                False,
                _SLOT_TTL_SECONDS + _SLOT_RENEW_INTERVAL_SECONDS,
                AdmissionOutcome.ADMITTED,
            ),
        ]
    )
    def test_held_slot_counts_only_while_its_process_renews_it(
        self, _name: str, renewed: bool, held_seconds: int, next_outcome: AdmissionOutcome
    ) -> None:
        self.get_settings.return_value = router_settings(mode=RouterMode.OBSERVE, limit=SMALL_LIMIT)
        with self._admit(QueryClass.BACKGROUND):
            for _ in range(held_seconds // _SLOT_RENEW_INTERVAL_SECONDS):
                self.clock.now += _SLOT_RENEW_INTERVAL_SECONDS
                if renewed:
                    self.router.renew_slots()
            with self._admit(QueryClass.BACKGROUND) as admission:
                assert admission.outcome == next_outcome

    def test_renewal_never_adds_a_slot_that_is_not_in_redis(self) -> None:
        with self._admit(QueryClass.API):
            self.redis.delete(running_key(Pool.OFFLINE, QueryClass.API))
            self.router.renew_slots()
            assert self._running(QueryClass.API) == 0

    def test_waiter_that_stopped_polling_stops_blocking_after_stale_ms(self) -> None:
        self._finish()
        stuck = _ParkedWaiter(self.clock, QueryClass.BACKGROUND)
        with ExitStack() as held:
            self._hold(held, 1)
            assert stuck.start() == "waiting"
        stuck_polled_at = self.clock.now

        self.clock.now += 0.1
        with self._admit(QueryClass.BACKGROUND) as admission:
            assert admission.outcome == AdmissionOutcome.ADMITTED_AFTER_WAIT
            assert STALE_WAITER_MS - 10 <= (self.clock.now - stuck_polled_at) * 1000 <= STALE_WAITER_MS + 510

        stuck.finish()

    @parameterized.expand(
        [
            ("slow_queries", SLOW_QUERY_SECONDS, AdmissionOutcome.WOULD_DROP),
            ("fast_queries", FAST_QUERY_SECONDS, AdmissionOutcome.WOULD_WAIT),
        ]
    )
    def test_observe_mode_admits_over_the_limit_and_holds_a_slot(
        self, _name: str, duration_seconds: float, expected_outcome: AdmissionOutcome
    ) -> None:
        self.get_settings.return_value = router_settings(mode=RouterMode.OBSERVE, limit=SMALL_LIMIT)
        self._finish(duration_seconds)
        with ExitStack() as held:
            self._hold(held, SMALL_LIMIT)
            started_at = self.clock.now
            with self._admit(QueryClass.BACKGROUND) as admission:
                assert admission.outcome == expected_outcome
                assert self.clock.now == started_at
                assert self._running(QueryClass.BACKGROUND) == 1
            assert self._running(QueryClass.BACKGROUND) == 0

    def test_router_failure_lets_the_query_through(self) -> None:
        server = fakeredis.FakeServer()
        router = QueryRouter(
            redis_client=fakeredis.FakeRedis(server=server), get_time=self.clock.time, sleep=self.clock.sleep
        )
        admission_errors = (
            "posthog_query_router_admissions_total",
            {"pool": "offline", "query_class": "api", "outcome": "error"},
        )
        release_errors = ("posthog_query_router_slot_errors_total", {"operation": "release"})
        admission_errors_before = _sample_value(*admission_errors)
        release_errors_before = _sample_value(*release_errors)

        with router.admit(pool=Pool.OFFLINE, query_class=QueryClass.API) as admission:
            assert admission.outcome == AdmissionOutcome.ADMITTED
            server.connected = False

        assert _sample_value(*admission_errors) == admission_errors_before
        assert _sample_value(*release_errors) == release_errors_before + 1

        with router.admit(pool=Pool.OFFLINE, query_class=QueryClass.API) as admission:
            assert admission.outcome == AdmissionOutcome.ERROR

        assert _sample_value(*admission_errors) == admission_errors_before + 1

        server.connected = True
        self.get_settings.return_value = router_settings(mode=RouterMode.ERROR, limit=SMALL_LIMIT)
        with router.admit(pool=Pool.OFFLINE, query_class=QueryClass.API) as admission:
            assert admission.outcome == AdmissionOutcome.ERROR

    def test_release_records_how_long_the_query_ran_and_keeps_the_last_hundred(self) -> None:
        for _ in range(DURATION_HISTORY + 1):
            with self._admit(QueryClass.API):
                self.clock.now += 1.5

        durations = self.redis.lrange(durations_key(Pool.OFFLINE), 0, -1)
        assert [int(duration) for duration in durations] == [1500] * DURATION_HISTORY

    def test_slot_is_released_when_the_query_raises(self) -> None:
        with self.assertRaises(ValueError):
            with self._admit(QueryClass.API):
                assert self._running(QueryClass.API) == 1
                raise ValueError("query failed")

        assert self._running(QueryClass.API) == 0
