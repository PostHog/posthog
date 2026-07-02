"""``limits``-backed implementation of the outbound limiter.

All limiter-library and Redis specifics live here so the facade and consumers stay
backend-agnostic — swap the library by replacing this module. A sliding-window-counter over Redis
holds the shared budget across worker processes: O(1) memory per key, self-expiring (no background
threads, nothing to groom). An in-memory counter is the degraded fallback when Redis is down.

``limits`` builds its storage from our shared sync ``posthog.redis`` client; the async ``acquire``
offloads the blocking call via ``asyncio.to_thread`` rather than pulling in ``limits``' async
storage, which requires a separate ``coredis`` client and would bypass our configured client.
"""

import asyncio
import threading

import structlog
import redis.exceptions
from limits import RateLimitItemPerSecond
from limits.storage import MemoryStorage, RedisStorage
from limits.strategies import SlidingWindowCounterRateLimiter

from posthog.egress.limiter.policies import Priority, RateLimit, RatePolicy
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# Transport failures we degrade to the in-memory fallback on; anything else (config/programming
# errors) propagates rather than being silently mislabeled as a Redis outage.
_REDIS_ERRORS = (redis.exceptions.RedisError, ConnectionError, TimeoutError, OSError)

# The connection_pool is what's actually used; this URI only has to parse as a redis URI.
_PLACEHOLDER_URI = "redis://outbound-rate-limiter"

# Namespace our keys in the shared Redis db so they're self-documenting and can't collide with
# (or be wiped by a reset() of) anything else that might use the limits library's default "LIMITS".
_KEY_PREFIX = "outbound_rate_limit"


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


class LimitsBackend:
    """Sliding-window-counter rate limiting over Redis with an in-memory fallback.

    One limiter instance is built lazily and reused for all keys — ``limits`` namespaces state in
    Redis by the key passed to ``hit``/``test``, so there are no per-key objects or background work.
    """

    def __init__(self) -> None:
        self._redis: SlidingWindowCounterRateLimiter | None = None
        self._memory: SlidingWindowCounterRateLimiter | None = None
        self._lock = threading.Lock()

    async def acquire(self, key: str, policy: RatePolicy, n: int, priority: Priority) -> bool:
        # Offload the blocking Redis call so the event loop isn't held.
        return await asyncio.to_thread(self.consume_sync, key, policy, n, priority)

    def consume_sync(self, key: str, policy: RatePolicy, n: int, priority: Priority) -> bool:
        try:
            limits = policy.limits
            return _check(self._redis_limiter(), _items(limits), key, n, _reserves(policy, priority, limits))
        except _REDIS_ERRORS:
            logger.warning("outbound_rate_limit_redis_unavailable", key=key, fallback="in_memory")
            # Reserve off the shrunk fallback budget so the floor scales with the smaller per-process
            # limit rather than the full one.
            shrunk = self._shrunk(policy)
            return _check(self._memory_limiter(), _items(shrunk), key, n, _reserves(policy, priority, shrunk))

    @staticmethod
    def _shrunk(policy: RatePolicy) -> tuple[RateLimit, ...]:
        divider = max(1, policy.in_memory_divider)
        return tuple((max(1, count // divider), period) for count, period in policy.limits)

    def _redis_limiter(self) -> SlidingWindowCounterRateLimiter:
        if self._redis is None:
            with self._lock:
                if self._redis is None:
                    storage = RedisStorage(
                        _PLACEHOLDER_URI, connection_pool=get_client().connection_pool, key_prefix=_KEY_PREFIX
                    )
                    self._redis = SlidingWindowCounterRateLimiter(storage)
        return self._redis

    def _memory_limiter(self) -> SlidingWindowCounterRateLimiter:
        if self._memory is None:
            with self._lock:
                if self._memory is None:
                    self._memory = SlidingWindowCounterRateLimiter(MemoryStorage())
        return self._memory
