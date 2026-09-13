"""Redis-backed token bucket for rate limiting.

A bucket holds up to ``burst`` tokens and refills continuously at
``per_hour / 3600`` tokens per second. Continuous refill is what a fixed
window cannot give: no 2x burst across a window boundary, no lockout until
the top of the hour, and ``retry_after`` is the real per-caller wait for the
next token rather than the time to the window edge.

Custom Lua rather than the vendored ``limits`` library because ``limits``
offers only window strategies (fixed/moving/sliding) with no token bucket and
no way to refund a charge, and stock Redis has no native rate-limit command.
The check-refill-and-charge sequence must be atomic across concurrent web
workers, which is exactly what a server-side script provides; ``limits``
ships its own Lua for the same reason.

Callers decide what happens when Redis can't answer: every operation returns
``BucketUnavailable`` instead of raising, so an endpoint can fail open (most
should) or fall through to a durable check without this module choosing for
them. Deliberately metric-free; counters belong with the consumer that knows
the endpoint and tier being limited.
"""

from __future__ import annotations

import math
import time

import structlog
from redis.exceptions import RedisError
from redis_lua_py import Key, redis, script

from posthog.dataclasses import frozen
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


@frozen
class Budget:
    # Capacity: the most tokens the bucket can hold, so the biggest burst a caller gets.
    burst: int
    # Refill rate, as tokens per hour.
    per_hour: int

    def __post_init__(self) -> None:
        if self.burst < 1:
            raise ValueError(f"burst must be >= 1, got {self.burst}")
        if self.per_hour < 1:
            raise ValueError(f"per_hour must be >= 1, got {self.per_hour}")

    @property
    def refill_per_second(self) -> float:
        return self.per_hour / 3600.0


@frozen
class BucketDecision:
    allowed: bool
    # Whole tokens currently available. ``limit`` is the capacity (``burst``),
    # matching RateLimit-Limit/Remaining header semantics for token buckets.
    remaining: int
    limit: int
    # Seconds until the next token exists (0 when allowed). Whole seconds,
    # rounded up, so a Retry-After header never tells a caller to retry early.
    retry_after: int
    # Seconds until the bucket is full again.
    reset: int


@frozen
class BucketUnavailable:
    """Redis could not answer. The caller chooses fail-open or a durable fallback."""

    error: str


@script
def _consume_tokens(bucket: Key, capacity: float, refill_per_second: float, cost: int, now_ms: float) -> list[int]:
    """Returns [allowed, remaining_floor, retry_after_ms, reset_ms]."""
    stored_tokens, stored_ts = redis.hmget(bucket, "tokens", "ts")
    if stored_tokens is None or stored_ts is None:
        tokens = capacity
        ts = now_ms
    else:
        tokens = float(stored_tokens)
        ts = float(stored_ts)

    # Clamp a backwards clock (web workers supply now_ms and may disagree by a
    # little) so a skewed worker can neither mint free tokens nor wipe accrual.
    if now_ms < ts:
        now_ms = ts
    tokens = min(capacity, tokens + ((now_ms - ts) / 1000.0) * refill_per_second)

    allowed = 0
    if tokens >= cost:
        tokens -= cost
        allowed = 1

    redis.hset(bucket, "tokens", tokens, "ts", now_ms)
    # Self-expire once the bucket would be full anyway, so idle keys don't accumulate.
    redis.pexpire(bucket, math.ceil((capacity / refill_per_second) * 1000) + 60000)

    retry_after_ms = 0
    if allowed == 0:
        retry_after_ms = math.ceil(((cost - tokens) / refill_per_second) * 1000)
    reset_ms = math.ceil(((capacity - tokens) / refill_per_second) * 1000)
    return [allowed, math.floor(tokens), retry_after_ms, reset_ms]


@script
def _refund_tokens(bucket: Key, capacity: float, cost: int) -> int:
    stored_tokens = redis.hget(bucket, "tokens")
    # A missing key means the bucket is already full, so there is nothing to give back.
    if stored_tokens is None:
        return math.floor(capacity)
    tokens = min(capacity, float(stored_tokens) + cost)
    redis.hset(bucket, "tokens", tokens)
    return math.floor(tokens)


def consume(key: str, budget: Budget, cost: int = 1) -> BucketDecision | BucketUnavailable:
    """Atomically refill the bucket and take ``cost`` tokens if available."""
    if cost < 1 or cost > budget.burst:
        raise ValueError(f"cost must be between 1 and burst ({budget.burst}), got {cost}")
    try:
        allowed, remaining, retry_after_ms, reset_ms = _consume_tokens(
            get_client(),
            bucket=key,
            capacity=budget.burst,
            refill_per_second=budget.refill_per_second,
            cost=cost,
            now_ms=int(time.time() * 1000),
        )
    except RedisError as e:
        logger.warning("token_bucket_unavailable", key=key, operation="consume", error=str(e))
        return BucketUnavailable(error=str(e))
    return BucketDecision(
        allowed=bool(allowed),
        remaining=int(remaining),
        limit=budget.burst,
        retry_after=math.ceil(retry_after_ms / 1000),
        reset=math.ceil(reset_ms / 1000),
    )


def refund(key: str, budget: Budget, cost: int = 1) -> int | BucketUnavailable:
    """Give ``cost`` tokens back, capped at capacity. Returns the new whole-token count."""
    if cost < 1:
        raise ValueError(f"cost must be >= 1, got {cost}")
    try:
        return int(_refund_tokens(get_client(), bucket=key, capacity=budget.burst, cost=cost))
    except RedisError as e:
        logger.warning("token_bucket_unavailable", key=key, operation="refund", error=str(e))
        return BucketUnavailable(error=str(e))


def peek(key: str, budget: Budget) -> BucketDecision | BucketUnavailable:
    """Read the bucket without charging it.

    A plain read plus local refill math instead of a third script: peek backs
    introspection and response headers, where losing a sub-second race to a
    concurrent charge changes nothing a caller may rely on.
    """
    try:
        tokens_raw, ts_raw = get_client().hmget(key, "tokens", "ts")
    except RedisError as e:
        logger.warning("token_bucket_unavailable", key=key, operation="peek", error=str(e))
        return BucketUnavailable(error=str(e))

    if tokens_raw is None or ts_raw is None:
        tokens = float(budget.burst)
    else:
        elapsed = max(0.0, time.time() - float(ts_raw) / 1000)
        tokens = min(float(budget.burst), float(tokens_raw) + elapsed * budget.refill_per_second)

    return BucketDecision(
        allowed=tokens >= 1,
        remaining=math.floor(tokens),
        limit=budget.burst,
        retry_after=0 if tokens >= 1 else math.ceil((1 - tokens) / budget.refill_per_second),
        reset=math.ceil((budget.burst - tokens) / budget.refill_per_second),
    )
