import os
import time
import uuid
import random
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import Literal

import structlog
from clickhouse_driver.errors import ErrorCodes
from prometheus_client import Counter, Histogram
from redis import Redis
from redis.exceptions import RedisError

from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import (
    ARRIVALS_WINDOW_MS,
    DURATION_HISTORY,
    MAX_WAIT_SECONDS,
    QUEUE_WAIT_MARGIN,
    RANK_CLASS_MULTIPLIER,
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
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.exceptions import ClickHouseAtCapacity
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

ADMISSIONS_COUNTER = Counter(
    "posthog_query_router_admissions_total",
    "Queries the query router admitted, dropped, or let through after an error.",
    labelnames=["pool", "query_class", "outcome"],
)

# Kept apart from ADMISSIONS_COUNTER, which counts each query once, at admission.
SLOT_ERRORS_COUNTER = Counter(
    "posthog_query_router_slot_errors_total",
    "Redis failures while the query router released or renewed slots.",
    labelnames=["operation"],
)

# Only refusals carry a team label, so the series count stays bounded by the teams that were refused.
DROPS_COUNTER = Counter(
    "posthog_query_router_drops_total",
    "Queries the query router refused, by team.",
    labelnames=["pool", "query_class", "team_id"],
)

WAIT_SECONDS_HISTOGRAM = Histogram(
    "posthog_query_router_wait_seconds",
    "Time an enforced query spent in the query router queue before it was admitted or dropped.",
    labelnames=["pool", "query_class"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)

# How full the pool is when queries arrive, which is what an operator compares with the limit setting.
RUNNING_HISTOGRAM = Histogram(
    "posthog_query_router_running",
    "Queries holding a slot in the pool when a routed query arrived.",
    labelnames=["pool"],
    buckets=(10, 25, 50, 75, 100, 125, 150, 200, 300, 400, 600, 800, 1000),
)

_BASE_POLL_DELAY_SECONDS = 0.05
# Stays well under STALE_WAITER_MS, so a waiter deep in the queue is never taken for gone between polls.
_MAX_POLL_DELAY_SECONDS = 1.0

# A slot counts for as long as its query runs, because the process that holds the slot renews it.
# The slot of a process that died stops counting within the time-to-live. Three renewals per
# time-to-live let a slot outlast one failed renewal.
_SLOT_TTL_SECONDS = 60
_SLOT_RENEW_INTERVAL_SECONDS = 20

_ERROR_LOG_INTERVAL_SECONDS = 60

# Every routed query calls Redis before it runs, so a slow Redis must fail open quickly instead of
# holding each query for the default socket timeout.
_REDIS_TIMEOUT_SECONDS = 1.0

# The router drops a query before it reaches ClickHouse, so a retry costs one Redis call and the pool
# can have room again within seconds. The error's default wait is longer because it covers a
# ClickHouse node that is over its own limit.
_RETRY_AFTER_SECONDS = (3, 8)

# KEYS[1] to KEYS[4] are the running sets in class order, so KEYS[my_class] is the caller's own set.
# KEYS[5] is waiting, KEYS[6] is waiting_seen, KEYS[7] is durations and KEYS[8] is arrivals. A rank
# arrives as a string and goes to Redis unchanged, and the script builds rank bounds with
# string.format('%.0f'), because Lua numbers are doubles and Lua prints a large number in scientific
# notation.
_TRY_ENTER_LUA = """
local now = tonumber(ARGV[1])
local slot = ARGV[2]
local my_class = tonumber(ARGV[3])
local rank = ARGV[4]
local rank_class_multiplier = tonumber(ARGV[5])
local limit = tonumber(ARGV[6])
local ttl_ms = tonumber(ARGV[7])
local stale_ms = tonumber(ARGV[8])
local enforcing = ARGV[9] == '1'
local first_attempt = ARGV[10] == '1'
local window_ms = tonumber(ARGV[11])
local wait_budget_ms = tonumber(ARGV[12])
local waiting = KEYS[5]
local waiting_seen = KEYS[6]
local durations = KEYS[7]
local arrivals = KEYS[8]

local function rank_of(query_class, ms)
    return string.format('%.0f', query_class * rank_class_multiplier + ms)
end

for i = 1, 4 do
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now)
end

local stale = redis.call('ZRANGEBYSCORE', waiting_seen, '-inf', now - stale_ms)
for _, stale_slot in ipairs(stale) do
    redis.call('ZREM', waiting, stale_slot)
    redis.call('ZREM', waiting_seen, stale_slot)
end

-- Arrivals share the rank's score, so each class's arrivals in the window are one score range.
if first_attempt then
    for i = 1, 4 do
        redis.call('ZREMRANGEBYSCORE', arrivals, rank_of(i, 0), '(' .. rank_of(i, now - window_ms))
    end
    redis.call('ZADD', arrivals, rank, slot)
end

local total = 0
for i = 1, 4 do
    total = total + redis.call('ZCARD', KEYS[i])
end

local ahead = redis.call('ZCOUNT', waiting, '-inf', '(' .. rank)

if total + ahead < limit then
    redis.call('ZADD', KEYS[my_class], now + ttl_ms, slot)
    redis.call('ZREM', waiting, slot)
    redis.call('ZREM', waiting_seen, slot)
    return {'admitted', total, ahead}
end

-- The estimate runs once, on arrival. A query already in the queue keeps its place until its deadline.
local refused = false
if first_attempt then
    -- The pool must free this many slots, net, before this query fits.
    local deficit = total + ahead - limit + 1
    local recent = redis.call('LRANGE', durations, 0, -1)
    local duration_sum = 0
    for _, duration_ms in ipairs(recent) do
        duration_sum = duration_sum + tonumber(duration_ms)
    end
    -- A higher class takes a freed slot before this query, whether it starts at once or queues ahead.
    local higher_arrivals = redis.call('ZCOUNT', arrivals, '-inf', '(' .. rank_of(my_class, 0))
    -- With no finished query to estimate from, the query waits out its budget.
    if duration_sum > 0 then
        -- Slots freed per millisecond: each of the limit's queries finishes after the average duration,
        -- less the freed slots that higher classes take.
        local net = limit * #recent / duration_sum - higher_arrivals / window_ms
        -- Without a positive net drain the wait has no bound, so the query is refused.
        refused = net <= 0 or deficit / net > wait_budget_ms
    end
end

if not enforcing then
    redis.call('ZADD', KEYS[my_class], now + ttl_ms, slot)
    if refused then
        return {'would_drop', total, ahead}
    end
    return {'would_wait', total, ahead}
end

if refused then
    return {'refused', total, ahead}
end

redis.call('ZADD', waiting, rank, slot)
redis.call('ZADD', waiting_seen, now, slot)
return {'wait', total, ahead}
"""

# KEYS are the slot's running set, waiting, waiting_seen and durations. One script for release and for
# leaving the queue keeps the two waiting sets consistent: a waiting entry without a waiting_seen entry
# is never found stale and would block every waiter behind it. Only a slot that left the running set ran
# a query, so only it records a duration.
_REMOVE_LUA = """
if redis.call('ZREM', KEYS[1], ARGV[1]) == 1 then
    redis.call('LPUSH', KEYS[4], ARGV[2])
    redis.call('LTRIM', KEYS[4], 0, tonumber(ARGV[3]) - 1)
end
redis.call('ZREM', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return 0
"""


class AdmissionOutcome(StrEnum):
    # The router is off for this pool and class and made no Redis call.
    OFF = "off"
    ADMITTED = "admitted"
    ADMITTED_AFTER_WAIT = "admitted_after_wait"
    # Observe mode: the query would have waited, but it runs and holds a slot.
    WOULD_WAIT = "would_wait"
    # Observe mode: the query would have been dropped on arrival, but it runs and holds a slot.
    WOULD_DROP = "would_drop"
    DROPPED_WAIT_TIMEOUT = "dropped_wait_timeout"
    # The pool drained too slowly for the query to start well within the wait.
    DROPPED_ON_ARRIVAL = "dropped_on_arrival"
    # Redis or the limit setting failed, so the query runs without a slot.
    ERROR = "error"


_SLOT_HOLDING_OUTCOMES = frozenset(
    {
        AdmissionOutcome.ADMITTED,
        AdmissionOutcome.ADMITTED_AFTER_WAIT,
        AdmissionOutcome.WOULD_WAIT,
        AdmissionOutcome.WOULD_DROP,
    }
)
_DROPPED_OUTCOMES = frozenset({AdmissionOutcome.DROPPED_WAIT_TIMEOUT, AdmissionOutcome.DROPPED_ON_ARRIVAL})


@frozen
class Admission:
    outcome: AdmissionOutcome
    waited_ms: int


_ROUTER_OFF = Admission(outcome=AdmissionOutcome.OFF, waited_ms=0)

_SlotOperation = Literal["release", "renew"]


class _Answer(StrEnum):
    ADMITTED = "admitted"
    WOULD_WAIT = "would_wait"
    WOULD_DROP = "would_drop"
    WAIT = "wait"
    REFUSED = "refused"


@frozen
class _Reply:
    answer: _Answer
    total: int
    # Waiters ranked before this one.
    ahead: int


@frozen
class _Decision:
    outcome: AdmissionOutcome
    reply: _Reply
    queued: bool


@frozen
class _Slot:
    pool: Pool
    query_class: QueryClass
    slot_id: str


def _class_label(query_class: QueryClass) -> str:
    return query_class.name.lower()


class QueryRouter:
    """Admits ClickHouse queries per node pool against a shared limit kept in Redis.

    Tests replace get_time and sleep with a fake clock. Only get_query_router starts the thread that
    renews held slots, so a router built directly renews them only when renew_slots is called.
    """

    def __init__(
        self,
        *,
        redis_client: Redis,
        get_time: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.get_time = get_time
        self.sleep = sleep
        self._redis = redis_client
        self._try_enter_script = redis_client.register_script(_TRY_ENTER_LUA)
        self._remove_script = redis_client.register_script(_REMOVE_LUA)
        self._last_error_logged_at: float | None = None
        # Query threads add and remove slots while the renewal thread reads them.
        self._held_slots: set[_Slot] = set()
        self._held_slots_lock = threading.Lock()

    def _elapsed_ms(self, started_at: float) -> int:
        return int((self.get_time() - started_at) * 1000)

    def _log_error(self, event: str, **fields: str) -> None:
        now = self.get_time()
        if self._last_error_logged_at is not None and now - self._last_error_logged_at < _ERROR_LOG_INTERVAL_SECONDS:
            return
        self._last_error_logged_at = now
        logger.warning(event, exc_info=True, **fields)

    def _fail_open(self, slot: _Slot, started_at: float) -> Admission:
        ADMISSIONS_COUNTER.labels(
            pool=slot.pool.value,
            query_class=_class_label(slot.query_class),
            outcome=AdmissionOutcome.ERROR.value,
        ).inc()
        self._log_error("query_router_failed_open", pool=slot.pool.value, query_class=_class_label(slot.query_class))
        return Admission(outcome=AdmissionOutcome.ERROR, waited_ms=self._elapsed_ms(started_at))

    def _record_slot_error(self, operation: _SlotOperation) -> None:
        SLOT_ERRORS_COUNTER.labels(operation=operation).inc()
        self._log_error("query_router_slot_error", operation=operation)

    def _remove(self, slot: _Slot, *, ran_ms: int) -> None:
        self._remove_script(
            keys=[
                running_key(slot.pool, slot.query_class),
                waiting_key(slot.pool),
                waiting_seen_key(slot.pool),
                durations_key(slot.pool),
            ],
            args=[slot.slot_id, ran_ms, DURATION_HISTORY],
        )

    def _release(self, slot: _Slot, *, admitted_at: float) -> None:
        try:
            self._remove(slot, ran_ms=self._elapsed_ms(admitted_at))
        except RedisError:
            self._record_slot_error("release")

    def _try_enter(self, slot: _Slot, *, rank: int, limit: int, enforcing: bool, first_attempt: bool) -> _Reply:
        answer, total, ahead = self._try_enter_script(
            keys=[
                *(running_key(slot.pool, query_class) for query_class in QueryClass),
                waiting_key(slot.pool),
                waiting_seen_key(slot.pool),
                durations_key(slot.pool),
                arrivals_key(slot.pool),
            ],
            args=[
                int(self.get_time() * 1000),
                slot.slot_id,
                int(slot.query_class),
                rank,
                RANK_CLASS_MULTIPLIER,
                limit,
                _SLOT_TTL_SECONDS * 1000,
                STALE_WAITER_MS,
                int(enforcing),
                int(first_attempt),
                ARRIVALS_WINDOW_MS,
                round(MAX_WAIT_SECONDS * 1000 * QUEUE_WAIT_MARGIN),
            ],
        )
        return _Reply(answer=_Answer(answer.decode()), total=int(total), ahead=int(ahead))

    def _poll(
        self,
        slot: _Slot,
        *,
        enforcing: bool,
        limit: int,
        started_at: float,
        cancellation_key: str | None,
    ) -> _Decision:
        deadline = started_at + MAX_WAIT_SECONDS
        # The rank keeps the first poll's time, so a waiter keeps its place in the queue on every poll.
        rank = int(slot.query_class) * RANK_CLASS_MULTIPLIER + int(started_at * 1000)
        queued = False
        while True:
            if queued and cancellation_key is not None:
                cancelled = self._redis.get(cancellation_key)
                if cancelled:
                    raise CHQueryErrorQueryWasCancelled("Query was cancelled", code=ErrorCodes.QUERY_WAS_CANCELLED)
            reply = self._try_enter(slot, rank=rank, limit=limit, enforcing=enforcing, first_attempt=not queued)
            if reply.answer == _Answer.ADMITTED:
                outcome = AdmissionOutcome.ADMITTED_AFTER_WAIT if queued else AdmissionOutcome.ADMITTED
                return _Decision(outcome=outcome, reply=reply, queued=queued)
            if reply.answer == _Answer.WOULD_WAIT:
                return _Decision(outcome=AdmissionOutcome.WOULD_WAIT, reply=reply, queued=False)
            if reply.answer == _Answer.WOULD_DROP:
                return _Decision(outcome=AdmissionOutcome.WOULD_DROP, reply=reply, queued=False)
            if reply.answer == _Answer.REFUSED:
                return _Decision(outcome=AdmissionOutcome.DROPPED_ON_ARRIVAL, reply=reply, queued=False)

            queued = True
            remaining = deadline - self.get_time()
            if remaining > 0:
                # The waiter at the head polls often, so it takes a freed slot almost at once. A waiter deep in
                # the queue polls rarely, which bounds the Redis load of a long queue.
                delay = min(_BASE_POLL_DELAY_SECONDS * (1 + reply.ahead), _MAX_POLL_DELAY_SECONDS)
                self.sleep(min(delay * random.uniform(0.5, 1.0), remaining))
            # A sleep can end late on a busy host. The waiter is dropped even when a slot has freed, so no
            # query waits longer than the budget.
            if self.get_time() >= deadline:
                self._remove(slot, ran_ms=0)
                return _Decision(outcome=AdmissionOutcome.DROPPED_WAIT_TIMEOUT, reply=reply, queued=True)

    def _enter(
        self,
        slot: _Slot,
        *,
        mode: RouterMode,
        limits: Mapping[Pool, int],
        team_id: int | None,
        cancellation_key: str | None,
    ) -> Admission:
        started_at = self.get_time()
        if mode == RouterMode.ERROR:
            return self._fail_open(slot, started_at)

        try:
            decision = self._poll(
                slot,
                enforcing=mode == RouterMode.ENFORCE,
                limit=limits[slot.pool],
                started_at=started_at,
                cancellation_key=cancellation_key,
            )
        except RedisError:
            admission = self._fail_open(slot, started_at)
            # The script may have added the slot before its reply was lost. Without this removal the
            # slot would count against the pool until its ttl.
            with suppress(RedisError):
                self._remove(slot, ran_ms=0)
            return admission
        except BaseException:
            # A waiter interrupted in its sleep, for example by a Celery soft time limit, would
            # otherwise stay in the queue and block the waiters behind it until it turns stale.
            with suppress(RedisError):
                self._remove(slot, ran_ms=0)
            raise

        waited_ms = self._elapsed_ms(started_at)
        ADMISSIONS_COUNTER.labels(
            pool=slot.pool.value,
            query_class=_class_label(slot.query_class),
            outcome=decision.outcome.value,
        ).inc()
        RUNNING_HISTOGRAM.labels(pool=slot.pool.value).observe(decision.reply.total)
        if decision.queued:
            WAIT_SECONDS_HISTOGRAM.labels(pool=slot.pool.value, query_class=_class_label(slot.query_class)).observe(
                waited_ms / 1000
            )
        if decision.outcome in _DROPPED_OUTCOMES:
            retry_after = random.randint(*_RETRY_AFTER_SECONDS)
            DROPS_COUNTER.labels(
                pool=slot.pool.value, query_class=_class_label(slot.query_class), team_id=str(team_id or "")
            ).inc()
            logger.info(
                "query_router_dropped",
                pool=slot.pool.value,
                query_class=_class_label(slot.query_class),
                team_id=team_id,
                outcome=decision.outcome.value,
                waited_ms=waited_ms,
                retry_after=retry_after,
            )
            raise ClickHouseAtCapacity(wait=retry_after)
        return Admission(outcome=decision.outcome, waited_ms=waited_ms)

    @contextmanager
    def admit(
        self,
        *,
        pool: Pool,
        query_class: QueryClass,
        team_id: int | None = None,
        cancellation_key: str | None = None,
    ) -> Iterator[Admission]:
        """Hold a slot in the pool while the block runs.

        Raises ClickHouseAtCapacity when the query is dropped and propagates cancellation.
        Redis and settings failures let the query run without a slot.
        """
        settings = config.get_settings()
        mode = settings.mode_for(pool, query_class)
        if mode == RouterMode.OFF:
            yield _ROUTER_OFF
            return

        slot = _Slot(pool=pool, query_class=query_class, slot_id=uuid.uuid4().hex)
        admission = self._enter(
            slot, mode=mode, limits=settings.limits, team_id=team_id, cancellation_key=cancellation_key
        )
        admitted_at = self.get_time()
        holds_slot = admission.outcome in _SLOT_HOLDING_OUTCOMES
        if holds_slot:
            with self._held_slots_lock:
                self._held_slots.add(slot)
        try:
            yield admission
        finally:
            if holds_slot:
                with self._held_slots_lock:
                    self._held_slots.remove(slot)
                self._release(slot, admitted_at=admitted_at)

    def renew_slots(self) -> None:
        with self._held_slots_lock:
            held_slots = list(self._held_slots)
        expires_at_ms = int(self.get_time() * 1000) + _SLOT_TTL_SECONDS * 1000
        expiries_by_key: defaultdict[str, dict[str | bytes, int]] = defaultdict(dict)
        for slot in held_slots:
            expiries_by_key[running_key(slot.pool, slot.query_class)][slot.slot_id] = expires_at_ms
        for key, expiries in expiries_by_key.items():
            try:
                # XX updates only the slots still in Redis, so a slot released after the snapshot above
                # stays released.
                self._redis.zadd(key, expiries, xx=True)
            except RedisError:
                self._record_slot_error("renew")


def _renew_slots_forever(router: QueryRouter) -> None:
    while True:
        time.sleep(_SLOT_RENEW_INTERVAL_SECONDS)
        try:
            router.renew_slots()
        except Exception:
            logger.exception("query_router_renewal_failed")


# The process id and the router built for that process.
_query_router: tuple[int, QueryRouter] | None = None
_query_router_lock = threading.Lock()


def get_query_router() -> QueryRouter:
    global _query_router
    pid = os.getpid()
    current = _query_router
    if current is not None and current[0] == pid:
        return current[1]
    with _query_router_lock:
        current = _query_router
        if current is not None and current[0] == pid:
            return current[1]
        # A forked child, such as a Celery prefork worker, inherits the router of its parent with the
        # slots the parent held at the fork, but not the renewal thread. The child builds its own
        # router so that it renews only its own slots.
        router = QueryRouter(
            redis_client=get_client(
                socket_timeout=_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_REDIS_TIMEOUT_SECONDS
            )
        )
        threading.Thread(
            target=_renew_slots_forever, args=(router,), name="query-router-slot-renewal", daemon=True
        ).start()
        _query_router = (pid, router)
        return router
