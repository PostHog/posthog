"""``limits``-backed implementation of the outbound limiter.

All limiter-library and Redis specifics live here so the facade and consumers stay
backend-agnostic — swap the library by replacing this module. A sliding-window-counter over Redis
holds the shared budget across worker processes: O(1) memory per key, self-expiring (no background
threads, nothing to groom). An in-memory counter is the degraded fallback when Redis is down.

``limits`` builds its storage from our shared sync ``posthog.redis`` client; the async ``acquire``
offloads the blocking call via ``asyncio.to_thread`` rather than pulling in ``limits``' async
storage, which requires a separate ``coredis`` client and would bypass our configured client.
"""

from __future__ import annotations

import time
import uuid
import asyncio
import threading
from typing import TYPE_CHECKING, cast

import structlog
import redis.exceptions
from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage, RedisStorage
from limits.strategies import SlidingWindowCounterRateLimiter

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority, RateLimit, RatePolicy
from posthog.redis import get_client

if TYPE_CHECKING:
    from redis.commands.core import Script

logger = structlog.get_logger(__name__)

# Transport failures we degrade to the in-memory fallback on; anything else (config/programming
# errors) propagates rather than being silently mislabeled as a Redis outage.
REDIS_ERRORS = (redis.exceptions.RedisError, ConnectionError, TimeoutError, OSError)

# The connection_pool is what's actually used; this URI only has to parse as a redis URI.
_PLACEHOLDER_URI = "redis://outbound-rate-limiter"

# Namespace our keys in the shared Redis db so they're self-documenting and can't collide with
# (or be wiped by a reset() of) anything else that might use the limits library's default "LIMITS".
_KEY_PREFIX = "outbound_rate_limit"

# While a window still holds more than this share of a priority's allowance, `pace_seconds` returns
# zero. A short run spends too little of the budget to exhaust it, so slowing it would buy nothing
# and cost latency on every small job. Under the share, the remaining allowance is close enough to
# the floor that spending it at full speed would exhaust the window and get the caller shed for the
# rest of it.
_PACE_HEADROOM_FRACTION = 0.5

# A fork of limits 5.8.0's resources/redis/lua_scripts/acquire_sliding_window.lua, which has no refund
# primitive; re-diff it on a limits upgrade, along with the private window-key shape it reads. Added
# here: a generation marker moved with its counter, so a release cannot decrement a later window.
_RESERVE_SLIDING_WINDOW = b"""
local limit = tonumber(ARGV[1])
local expiry = tonumber(ARGV[2]) * 1000
local amount = tonumber(ARGV[3])
local candidate_generation = ARGV[4]

if amount > limit then
    return false
end

local shift_ttl = tonumber(redis.call('pttl', KEYS[2]))
if shift_ttl > 0 and shift_ttl < expiry then
    redis.call('rename', KEYS[2], KEYS[1])
    if redis.call('exists', KEYS[4]) == 1 then
        redis.call('rename', KEYS[4], KEYS[3])
    else
        redis.call('del', KEYS[3])
    end
    redis.call('set', KEYS[2], 0, 'PX', shift_ttl + expiry)
    redis.call('set', KEYS[4], candidate_generation, 'PX', shift_ttl + expiry)
end

local previous_count = tonumber(redis.call('get', KEYS[1])) or 0
local previous_ttl = math.max(tonumber(redis.call('pttl', KEYS[1])) or 0, 0)
local current_count = tonumber(redis.call('get', KEYS[2])) or 0
local current_ttl = math.max(tonumber(redis.call('pttl', KEYS[2])) or 0, 0)

local weighted_count = math.floor(previous_count * previous_ttl / expiry) + current_count
if (weighted_count + amount) > limit then
    return false
end

if redis.call('exists', KEYS[2]) == 1 then
    redis.call('incrby', KEYS[2], amount)
    if redis.call('exists', KEYS[4]) == 0 then
        redis.call('set', KEYS[4], candidate_generation, 'PX', math.max(current_ttl, 1))
    end
else
    redis.call('set', KEYS[2], amount, 'PX', expiry * 2)
    redis.call('set', KEYS[4], candidate_generation, 'PX', expiry * 2)
end

return redis.call('get', KEYS[4])
"""

_RELEASE_SLIDING_WINDOW = b"""
local generation = ARGV[1]
local amount = tonumber(ARGV[2])

for index = 1, 2 do
    local count_key = KEYS[index]
    local generation_key = KEYS[index + 2]
    if redis.call('get', generation_key) == generation then
        local count = tonumber(redis.call('get', count_key)) or 0
        if count < amount then
            return false
        end
        redis.call('decrby', count_key, amount)
        return true
    end
end

return false
"""


@frozen
class RedisWindowReservation:
    item_key: str
    generation: str


@frozen
class LimitsReleaseToken:
    reservation_id: str
    windows: tuple[RedisWindowReservation, ...]
    amount: int
    ttl_seconds: int


def _items(limits: tuple[RateLimit, ...]) -> list[RateLimitItemPerSecond]:
    # limits models a window as amount-per-(multiples seconds); our periods are already seconds.
    return [RateLimitItemPerSecond(count, int(period_seconds)) for count, period_seconds in limits]


def _reserves(policy: RatePolicy, priority: Priority, limits: tuple[RateLimit, ...]) -> list[int]:
    # Per-window headroom (in units) this priority must leave free, parallel to _items. Goes through
    # RatePolicy.reserve_amount so admission and the facade's _validate share one floor formula.
    return [policy.reserve_amount(priority, count) for count, _ in limits]


def _check(
    limiter: SlidingWindowCounterRateLimiter,
    items: list[RateLimitItemPerSecond],
    key: str,
    n: int,
    reserves: list[int],
) -> bool:
    # Allowed only if every window has room for n PLUS the priority's reserved floor; if so, consume
    # only the real n. test inflates the cost by the reserve so lower-priority calls are denied while
    # that headroom is still owed to higher-priority traffic — but hit never charges the reserve, so
    # the budget stays shared (no per-priority buckets). CRITICAL/no-reserve => reserve 0 => test and
    # hit both cost n, the original behavior exactly.
    #
    # Best-effort, not atomic across windows: testing all first avoids the deterministic
    # partial-consume (hit window A, then deny window B), but a concurrent caller landing between test
    # and hit can still leave one window consumed on a denied call. The drift is deny-biased (we err
    # toward denying, never over-allowing the shared budget) and bounded by headroom plus the
    # consumer's reactive backoff — fine for egress; cross-window atomicity (a custom multi-window Lua)
    # isn't worth it at v1.
    if not all(limiter.test(item, key, cost=n + reserve) for item, reserve in zip(items, reserves)):
        return False
    return all(limiter.hit(item, key, cost=n) for item in items)


def _window_wait(
    limiter: SlidingWindowCounterRateLimiter,
    item: RateLimitItemPerSecond,
    key: str,
    count: int,
    reserve: int,
    now: float,
) -> float:
    """Seconds this window wants between calls so its allowance lasts until the window rolls.

    The budget is a sliding window, so it frees continuously rather than at a reset. A caller that
    waits for a reset would idle for a whole window; the useful wait is the interval that spreads
    the allowance that is left over the time that is left.
    """
    stats = limiter.get_window_stats(item, key)
    # The reserved floor is headroom this priority may not take, so it is not part of the allowance
    # being spread. Ignoring it would pace as if the whole window were available and still leave the
    # caller shed at the floor.
    usable = max(0, stats.remaining - reserve)
    if usable > (count - reserve) * _PACE_HEADROOM_FRACTION:
        return 0.0
    seconds_left = max(0.0, stats.reset_time - now)
    if usable == 0:
        return seconds_left
    return seconds_left / usable


class LimitsBackend:
    """Sliding-window-counter rate limiting over Redis with an in-memory fallback.

    One limiter instance is built lazily and reused for all keys — ``limits`` namespaces state in
    Redis by the key passed to ``hit``/``test``, so there are no per-key objects or background work.
    """

    def __init__(self) -> None:
        self._redis: SlidingWindowCounterRateLimiter | None = None
        self._memory: SlidingWindowCounterRateLimiter | None = None
        self._reserve_script: Script | None = None
        self._release_script: Script | None = None
        self._lock = threading.Lock()

    async def acquire(self, key: str, policy: RatePolicy, n: int, priority: Priority) -> bool:
        # Offload the blocking Redis call so the event loop isn't held.
        return await asyncio.to_thread(self.consume_sync, key, policy, n, priority)

    async def reserve(
        self, key: str, policy: RatePolicy, n: int, priority: Priority
    ) -> tuple[bool, LimitsReleaseToken | None]:
        return await asyncio.to_thread(self.reserve_sync, key, policy, n, priority)

    def consume_sync(self, key: str, policy: RatePolicy, n: int, priority: Priority) -> bool:
        try:
            limits = policy.limits
            return _check(self._redis_limiter(), _items(limits), key, n, _reserves(policy, priority, limits))
        except REDIS_ERRORS:
            logger.warning("outbound_rate_limit_redis_unavailable", key=key, fallback="in_memory")
            # Reserve off the shrunk fallback budget so the floor scales with the smaller per-process
            # limit rather than the full one.
            shrunk = self._shrunk(policy)
            return _check(self._memory_limiter(), _items(shrunk), key, n, _reserves(policy, priority, shrunk))

    def reserve_sync(
        self, key: str, policy: RatePolicy, n: int, priority: Priority
    ) -> tuple[bool, LimitsReleaseToken | None]:
        try:
            limits = policy.limits
            reservations: list[RedisWindowReservation] = []
            for item, reserve in zip(_items(limits), _reserves(policy, priority, limits)):
                reservation = self._reserve_redis_window(item, key, n, reserve)
                if reservation is None:
                    self._release_redis_windows(tuple(reservations), n)
                    return False, None
                reservations.append(reservation)
            return True, LimitsReleaseToken(
                reservation_id=uuid.uuid4().hex,
                windows=tuple(reservations),
                amount=n,
                ttl_seconds=int(max(period for _, period in limits)) * 2,
            )
        except REDIS_ERRORS:
            logger.warning("outbound_rate_limit_redis_unavailable", key=key, fallback="in_memory")
            shrunk = self._shrunk(policy)
            granted = _check(self._memory_limiter(), _items(shrunk), key, n, _reserves(policy, priority, shrunk))
            return granted, None

    def release_sync(self, token: LimitsReleaseToken) -> bool:
        try:
            claimed = get_client().set(
                f"{_KEY_PREFIX}:released:{token.reservation_id}", "1", ex=token.ttl_seconds, nx=True
            )
            if not claimed:
                return False
            return self._release_redis_windows(token.windows, token.amount)
        except REDIS_ERRORS:
            return False

    def pace_seconds(self, key: str, policy: RatePolicy, priority: Priority) -> float:
        limits = policy.limits
        try:
            limiter = self._redis_limiter()
            now = time.time()
            waits = [
                _window_wait(limiter, item, key, count, reserve, now)
                for item, (count, _), reserve in zip(_items(limits), limits, _reserves(policy, priority, limits))
            ]
        except REDIS_ERRORS:
            # The in-memory fallback counts one process, so its headroom is not the shared budget's
            # and a wait derived from it would be a guess. Zero leaves the gate and the caller's own
            # backoff behaving exactly as they do without pacing.
            return 0.0
        # The tightest window governs: waiting the shortest interval would exhaust every other one.
        return max(waits, default=0.0)

    @staticmethod
    def _shrunk(policy: RatePolicy) -> tuple[RateLimit, ...]:
        divider = max(1, policy.in_memory_divider)
        return tuple((max(1, count // divider), period) for count, period in policy.limits)

    def _reserve_redis_window(
        self, item: RateLimitItemPerSecond, key: str, n: int, reserve: int
    ) -> RedisWindowReservation | None:
        item_key = item.key_for(key)
        reserve_window, _ = self._scripts()
        generation = reserve_window(
            keys=self._redis_window_keys(item_key),
            args=[item.amount - reserve, item.get_expiry(), n, uuid.uuid4().hex],
        )
        if not generation:
            return None
        return RedisWindowReservation(item_key=item_key, generation=bytes(generation).decode())

    def _release_redis_windows(self, reservations: tuple[RedisWindowReservation, ...], amount: int) -> bool:
        _, release = self._scripts()
        released = True
        for reservation in reservations:
            if not release(keys=self._redis_window_keys(reservation.item_key), args=[reservation.generation, amount]):
                released = False
        return released

    def _redis_window_keys(self, item_key: str) -> list[str]:
        """The four keys both scripts take, in KEYS order: previous, current, and their generations."""
        storage = self._redis_storage()
        previous_key = storage.prefixed_key(storage._previous_window_key(item_key))
        current_key = storage.prefixed_key(storage._current_window_key(item_key))
        return [previous_key, current_key, f"{previous_key}:generation", f"{current_key}:generation"]

    def _redis_storage(self) -> RedisStorage:
        return cast(RedisStorage, self._redis_limiter().storage)

    def _scripts(self) -> tuple[Script, Script]:
        self._redis_limiter()
        assert self._reserve_script is not None and self._release_script is not None
        return self._reserve_script, self._release_script

    def _redis_limiter(self) -> SlidingWindowCounterRateLimiter:
        if self._redis is None:
            with self._lock:
                if self._redis is None:
                    storage = RedisStorage(
                        _PLACEHOLDER_URI, connection_pool=get_client().connection_pool, key_prefix=_KEY_PREFIX
                    )
                    self._reserve_script = storage.get_connection().register_script(_RESERVE_SLIDING_WINDOW)
                    self._release_script = storage.get_connection().register_script(_RELEASE_SLIDING_WINDOW)
                    self._redis = SlidingWindowCounterRateLimiter(storage)
        return self._redis

    def _memory_limiter(self) -> SlidingWindowCounterRateLimiter:
        if self._memory is None:
            with self._lock:
                if self._memory is None:
                    self._memory = SlidingWindowCounterRateLimiter(MemoryStorage())
        return self._memory
