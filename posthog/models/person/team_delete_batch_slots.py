import time
import uuid
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import structlog
from prometheus_client import Gauge
from redis.exceptions import RedisError

from posthog import redis

logger = structlog.get_logger(__name__)

# The hash tag keeps the three keys in one Redis Cluster hash slot, which the acquire script needs.
SLOTS_KEY = "{team_delete_persons}:slots"
QUEUE_KEY = "{team_delete_persons}:queue"
WAITERS_KEY = "{team_delete_persons}:waiters"
SLOT_TTL_SECONDS = 30
RENEW_SECONDS = 5
# Several renewals that each hit this timeout still fit inside SLOT_TTL_SECONDS.
REDIS_TIMEOUT_SECONDS = 2
WAITER_TTL_SECONDS = 10
POLL_SECONDS = 0.2
MAX_WAIT_SECONDS = 5 * 60

# A caller gets a slot only when fewer callers wait before it than there are free slots.
# KEYS: slots (scored by expiry), queue (scored by the time each caller started to wait), waiters (scored by expiry).
# ARGV: now, slot expiry, caller id, max concurrent slots, waiter expiry.
_ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
for _, waiter in ipairs(redis.call('ZRANGEBYSCORE', KEYS[3], '-inf', now)) do
    redis.call('ZREM', KEYS[2], waiter)
end
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
redis.call('ZADD', KEYS[2], 'NX', now, ARGV[3])
redis.call('ZADD', KEYS[3], ARGV[5], ARGV[3])
local free = tonumber(ARGV[4]) - redis.call('ZCARD', KEYS[1])
if free <= 0 or redis.call('ZRANK', KEYS[2], ARGV[3]) >= free then
    return 0
end
redis.call('ZREM', KEYS[2], ARGV[3])
redis.call('ZREM', KEYS[3], ARGV[3])
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[3])
return 1
"""

MAX_CONCURRENT_BATCHES_GAUGE = Gauge(
    "posthog_team_delete_persons_max_concurrent_batches",
    "Persons batches that team deletions may run at once across all workers in the region.",
)


class BatchSlotWaitTimeout(Exception):
    """No batch slot came free within the wait limit."""


class TeamDeletePersonsBatchSlots:
    """Caps the persons batches that team deletions run at once across every worker in the region.

    Slots go out in the order that callers started to wait, so a job that releases a slot waits behind
    the jobs that already wait. ``max_concurrent`` is read on every poll, so a change to the cap applies
    to the jobs that already wait. Run each batch inside ``hold``, which renews the slot while the batch
    runs, so the slot TTL frees only the slot of a worker that died or lost Redis. ``clock`` must be
    wall-clock time, because the scores that different hosts write are compared in the same sorted sets.
    """

    def __init__(
        self,
        max_concurrent: Callable[[], int],
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        renew_seconds: float = RENEW_SECONDS,
        max_wait_seconds: float = MAX_WAIT_SECONDS,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._clock = clock
        self._sleep = sleep
        self._renew_seconds = renew_seconds
        self._max_wait_seconds = max_wait_seconds
        self._redis = redis.get_client(
            socket_timeout=REDIS_TIMEOUT_SECONDS, socket_connect_timeout=REDIS_TIMEOUT_SECONDS
        )

    def acquire(self, should_stop: Callable[[], bool] | None = None) -> str | None:
        """Wait for a free slot and return its id, or return None when ``should_stop`` asks to stop first.

        Raises ``BatchSlotWaitTimeout`` after ``max_wait_seconds``, so that a paused or crowded cap does not
        keep a worker thread for the whole wait. The activity retry asks again later.
        """
        slot_id = uuid.uuid4().hex
        give_up_at = self._clock() + self._max_wait_seconds
        while not self._try_acquire(slot_id):
            if should_stop is not None and should_stop():
                self._leave_queue(slot_id)
                return None
            if self._clock() >= give_up_at:
                self._leave_queue(slot_id)
                raise BatchSlotWaitTimeout(f"No persons batch slot came free within {self._max_wait_seconds} s")
            self._sleep(POLL_SECONDS)
        return slot_id

    @contextmanager
    def hold(self, slot_id: str) -> Iterator[None]:
        """Renew the slot while the block runs, and release the slot when the block ends."""
        stop = threading.Event()
        renewer = threading.Thread(
            target=self._renew_until_stopped,
            args=(slot_id, stop),
            name="team-delete-persons-slot-renewer",
            daemon=True,
        )
        renewer.start()
        try:
            yield
        finally:
            stop.set()
            # A renewal after the release would add the slot back.
            renewer.join()
            self.release(slot_id)

    def release(self, slot_id: str) -> None:
        try:
            self._redis.zrem(SLOTS_KEY, slot_id)
        except RedisError:
            logger.warning("team_delete_persons_slot_release_failed", slot_id=slot_id, exc_info=True)

    def _renew_until_stopped(self, slot_id: str, stop: threading.Event) -> None:
        while not stop.wait(self._renew_seconds):
            try:
                # No XX: a slot that expired while Redis was unreachable comes back, because its batch still runs.
                self._redis.zadd(SLOTS_KEY, {slot_id: self._clock() + SLOT_TTL_SECONDS})
            except RedisError:
                logger.warning("team_delete_persons_slot_renewal_failed", slot_id=slot_id, exc_info=True)

    def _leave_queue(self, slot_id: str) -> None:
        pipeline = self._redis.pipeline()
        pipeline.zrem(QUEUE_KEY, slot_id)
        pipeline.zrem(WAITERS_KEY, slot_id)
        pipeline.execute()

    def _try_acquire(self, slot_id: str) -> bool:
        max_concurrent = max(0, self._max_concurrent())
        MAX_CONCURRENT_BATCHES_GAUGE.set(max_concurrent)
        now = self._clock()
        acquired = self._redis.eval(
            _ACQUIRE_SCRIPT,
            3,
            SLOTS_KEY,
            QUEUE_KEY,
            WAITERS_KEY,
            now,
            now + SLOT_TTL_SECONDS,
            slot_id,
            max_concurrent,
            now + WAITER_TTL_SECONDS,
        )
        return acquired == 1
