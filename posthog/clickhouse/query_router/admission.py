import os
import time
import uuid
import random
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from typing import Literal

import structlog
from prometheus_client import Counter, Histogram
from redis import Redis
from redis.exceptions import RedisError

from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import (
    CLASS_POLICIES,
    RANK_CLASS_MULTIPLIER,
    STALE_WAITER_MS,
    ClassPolicy,
    Pool,
    QueryClass,
    RouterMode,
    limit_key,
    running_key,
    waiting_key,
    waiting_seen_key,
)
from posthog.dataclasses import frozen
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

WAIT_SECONDS_HISTOGRAM = Histogram(
    "posthog_query_router_wait_seconds",
    "Time an enforced query spent in the query router queue before it was admitted or dropped.",
    labelnames=["pool", "query_class"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
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

# KEYS[1] to KEYS[4] are the running sets in class order, so KEYS[my_class] is the caller's own set.
# KEYS[5] is waiting, KEYS[6] is waiting_seen and KEYS[7] is the limit. Ranks and rank bounds arrive
# as strings and go to Redis unchanged, because Lua numbers are doubles.
_TRY_ENTER_LUA = """
local now = tonumber(ARGV[1])
local slot = ARGV[2]
local my_class = tonumber(ARGV[3])
local rank = ARGV[4]
local class_rank_min = ARGV[5]
local next_class_rank_min = ARGV[6]
local ceiling = ARGV[7]
local share_per_mille = tonumber(ARGV[8])
local ttl_ms = tonumber(ARGV[9])
local stale_ms = tonumber(ARGV[10])
local enforcing = ARGV[11] == '1'
local max_queue_depth = tonumber(ARGV[12])
local waiting = KEYS[5]
local waiting_seen = KEYS[6]

for i = 1, 4 do
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now)
end

local stale = redis.call('ZRANGEBYSCORE', waiting_seen, '-inf', now - stale_ms)
for _, stale_slot in ipairs(stale) do
    redis.call('ZREM', waiting, stale_slot)
    redis.call('ZREM', waiting_seen, stale_slot)
end

local limit = tonumber(redis.call('GET', KEYS[7]) or ceiling)

local total = 0
for i = 1, 4 do
    total = total + redis.call('ZCARD', KEYS[i])
end
-- Integer arithmetic, because a float share puts some products just under a whole number
-- (90 * 0.7 is 62.99... in floating point).
local allowed = math.floor(limit * share_per_mille / 1000)

local ahead = redis.call('ZCOUNT', waiting, '-inf', '(' .. rank)

if total + ahead < allowed then
    redis.call('ZADD', KEYS[my_class], now + ttl_ms, slot)
    redis.call('ZREM', waiting, slot)
    redis.call('ZREM', waiting_seen, slot)
    return {'admitted', total, limit, ahead}
end

if not enforcing then
    redis.call('ZADD', KEYS[my_class], now + ttl_ms, slot)
    return {'would_wait', total, limit, ahead}
end

if redis.call('ZSCORE', waiting, slot) then
    redis.call('ZADD', waiting_seen, now, slot)
    return {'wait', total, limit, ahead}
end

if redis.call('ZCOUNT', waiting, class_rank_min, '(' .. next_class_rank_min) >= max_queue_depth then
    return {'queue_full', total, limit, ahead}
end

redis.call('ZADD', waiting, rank, slot)
redis.call('ZADD', waiting_seen, now, slot)
return {'wait', total, limit, ahead}
"""

# KEYS are the slot's running set, waiting and waiting_seen. One script for release and for leaving
# the queue keeps the two waiting sets consistent: a waiting entry without a waiting_seen entry is
# never found stale and would block every waiter behind it.
_REMOVE_LUA = """
for i = 1, 3 do
    redis.call('ZREM', KEYS[i], ARGV[1])
end
return 0
"""


class AdmissionOutcome(StrEnum):
    # The router is off for this pool and class and made no Redis call.
    OFF = "off"
    ADMITTED = "admitted"
    ADMITTED_AFTER_WAIT = "admitted_after_wait"
    # Observe mode: the query would have waited, but it runs and holds a slot.
    WOULD_WAIT = "would_wait"
    DROPPED_WAIT_TIMEOUT = "dropped_wait_timeout"
    DROPPED_QUEUE_FULL = "dropped_queue_full"
    # Redis or the pool bounds failed, so the query runs without a slot.
    ERROR = "error"


_SLOT_HOLDING_OUTCOMES = frozenset(
    {AdmissionOutcome.ADMITTED, AdmissionOutcome.ADMITTED_AFTER_WAIT, AdmissionOutcome.WOULD_WAIT}
)
_DROPPED_OUTCOMES = frozenset({AdmissionOutcome.DROPPED_WAIT_TIMEOUT, AdmissionOutcome.DROPPED_QUEUE_FULL})


@frozen
class Admission:
    outcome: AdmissionOutcome
    waited_ms: int
    # Queries running in the pool and the pool limit at the last poll. None when no poll answered.
    total: int | None
    limit: int | None


_ROUTER_OFF = Admission(outcome=AdmissionOutcome.OFF, waited_ms=0, total=None, limit=None)

_SlotOperation = Literal["release", "renew"]


class _Answer(StrEnum):
    ADMITTED = "admitted"
    WOULD_WAIT = "would_wait"
    WAIT = "wait"
    QUEUE_FULL = "queue_full"


@frozen
class _Reply:
    answer: _Answer
    total: int
    limit: int
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
        return Admission(outcome=AdmissionOutcome.ERROR, waited_ms=self._elapsed_ms(started_at), total=None, limit=None)

    def _record_slot_error(self, operation: _SlotOperation) -> None:
        SLOT_ERRORS_COUNTER.labels(operation=operation).inc()
        self._log_error("query_router_slot_error", operation=operation)

    def _remove(self, slot: _Slot) -> None:
        self._remove_script(
            keys=[running_key(slot.pool, slot.query_class), waiting_key(slot.pool), waiting_seen_key(slot.pool)],
            args=[slot.slot_id],
        )

    def _release(self, slot: _Slot) -> None:
        try:
            self._remove(slot)
        except RedisError:
            self._record_slot_error("release")

    def _try_enter(self, slot: _Slot, *, policy: ClassPolicy, rank: int, ceiling: int, enforcing: bool) -> _Reply:
        class_rank_min = int(slot.query_class) * RANK_CLASS_MULTIPLIER
        answer, total, limit, ahead = self._try_enter_script(
            keys=[
                *(running_key(slot.pool, query_class) for query_class in QueryClass),
                waiting_key(slot.pool),
                waiting_seen_key(slot.pool),
                limit_key(slot.pool),
            ],
            args=[
                int(self.get_time() * 1000),
                slot.slot_id,
                int(slot.query_class),
                rank,
                class_rank_min,
                class_rank_min + RANK_CLASS_MULTIPLIER,
                ceiling,
                round(policy.share * 1000),
                _SLOT_TTL_SECONDS * 1000,
                STALE_WAITER_MS,
                int(enforcing),
                policy.max_queue_depth,
            ],
        )
        return _Reply(answer=_Answer(answer.decode()), total=int(total), limit=int(limit), ahead=int(ahead))

    def _poll(self, slot: _Slot, *, enforcing: bool, ceiling: int, started_at: float) -> _Decision:
        policy = CLASS_POLICIES[slot.query_class]
        deadline = started_at + policy.max_wait_seconds
        # The rank keeps the first poll's time, so a waiter keeps its place in the queue on every poll.
        rank = int(slot.query_class) * RANK_CLASS_MULTIPLIER + int(started_at * 1000)
        queued = False
        while True:
            reply = self._try_enter(slot, policy=policy, rank=rank, ceiling=ceiling, enforcing=enforcing)
            if reply.answer == _Answer.ADMITTED:
                outcome = AdmissionOutcome.ADMITTED_AFTER_WAIT if queued else AdmissionOutcome.ADMITTED
                return _Decision(outcome=outcome, reply=reply, queued=queued)
            if reply.answer == _Answer.WOULD_WAIT:
                return _Decision(outcome=AdmissionOutcome.WOULD_WAIT, reply=reply, queued=False)
            if reply.answer == _Answer.QUEUE_FULL:
                return _Decision(outcome=AdmissionOutcome.DROPPED_QUEUE_FULL, reply=reply, queued=queued)

            queued = True
            remaining = deadline - self.get_time()
            if remaining > 0:
                # The waiter at the head polls often, so it takes a freed slot almost at once. A waiter deep in
                # the queue polls rarely, which bounds the Redis load of a long queue.
                delay = min(_BASE_POLL_DELAY_SECONDS * (1 + reply.ahead), _MAX_POLL_DELAY_SECONDS)
                self.sleep(min(delay * random.uniform(0.5, 1.0), remaining))
            # A sleep can end late on a busy host. The waiter is dropped even when a slot has freed, so no
            # query waits longer than its class allows.
            if self.get_time() >= deadline:
                self._remove(slot)
                return _Decision(outcome=AdmissionOutcome.DROPPED_WAIT_TIMEOUT, reply=reply, queued=True)

    def _enter(self, slot: _Slot, *, enforcing: bool) -> Admission:
        started_at = self.get_time()
        try:
            ceiling = config.get_pool_bounds(slot.pool).ceiling
        except Exception:
            # A malformed or unreadable instance setting must not fail every query.
            return self._fail_open(slot, started_at)

        try:
            decision = self._poll(slot, enforcing=enforcing, ceiling=ceiling, started_at=started_at)
        except RedisError:
            admission = self._fail_open(slot, started_at)
            # The script may have added the slot before its reply was lost. Without this removal the
            # slot would count against the pool until its ttl.
            with suppress(RedisError):
                self._remove(slot)
            return admission
        except BaseException:
            # A waiter interrupted in its sleep, for example by a Celery soft time limit, would
            # otherwise stay in the queue and block the waiters behind it until it turns stale.
            with suppress(RedisError):
                self._remove(slot)
            raise

        waited_ms = self._elapsed_ms(started_at)
        ADMISSIONS_COUNTER.labels(
            pool=slot.pool.value,
            query_class=_class_label(slot.query_class),
            outcome=decision.outcome.value,
        ).inc()
        if decision.queued:
            WAIT_SECONDS_HISTOGRAM.labels(pool=slot.pool.value, query_class=_class_label(slot.query_class)).observe(
                waited_ms / 1000
            )
        if decision.outcome in _DROPPED_OUTCOMES:
            raise ClickHouseAtCapacity()
        return Admission(
            outcome=decision.outcome,
            waited_ms=waited_ms,
            total=decision.reply.total,
            limit=decision.reply.limit,
        )

    @contextmanager
    def admit(self, *, pool: Pool, query_class: QueryClass) -> Iterator[Admission]:
        """Hold a slot in the pool while the block runs.

        Raises ClickHouseAtCapacity when the query is dropped. Any other failure of the router lets
        the query run without a slot.
        """
        mode = config.get_mode(pool, query_class)
        if mode == RouterMode.OFF:
            yield _ROUTER_OFF
            return

        slot = _Slot(pool=pool, query_class=query_class, slot_id=uuid.uuid4().hex)
        admission = self._enter(slot, enforcing=mode == RouterMode.ENFORCE)
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
                self._release(slot)

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
