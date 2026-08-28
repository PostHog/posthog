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
from redis.commands.core import Script
from redis.exceptions import RedisError

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


# KEYS[1] bucket hash. ARGV: capacity, refill_per_sec, cost, now_ms.
# Returns {allowed, remaining_floor, retry_after_ms, reset_ms}.
_CONSUME_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now_ms = tonumber(ARGV[4])

local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
    tokens = capacity
    ts = now_ms
end

-- Clamp a backwards clock (web workers supply now_ms and may disagree by a
-- little) so a skewed worker can neither mint free tokens nor wipe accrual.
if now_ms < ts then
    now_ms = ts
end
tokens = math.min(capacity, tokens + ((now_ms - ts) / 1000.0) * refill_per_sec)

local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now_ms)
-- Self-expire once the bucket would be full anyway, so idle keys don't accumulate.
redis.call('PEXPIRE', KEYS[1], math.ceil((capacity / refill_per_sec) * 1000) + 60000)

local retry_after_ms = 0
if allowed == 0 then
    retry_after_ms = math.ceil(((cost - tokens) / refill_per_sec) * 1000)
end
local reset_ms = math.ceil(((capacity - tokens) / refill_per_sec) * 1000)
return {allowed, math.floor(tokens), retry_after_ms, reset_ms}
"""

# KEYS[1] bucket hash. ARGV: capacity, cost.
# A missing key means the bucket is already full, so there is nothing to give back.
_REFUND_LUA = """
local capacity = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
if tokens == nil then
    return capacity
end
tokens = math.min(capacity, tokens + cost)
redis.call('HSET', KEYS[1], 'tokens', tokens)
return math.floor(tokens)
"""


@frozen
class _Scripts:
    consume: Script
    refund: Script


_registered_scripts: _Scripts | None = None


def _scripts() -> _Scripts:
    global _registered_scripts
    if _registered_scripts is None:
        client = get_client()
        _registered_scripts = _Scripts(
            consume=client.register_script(_CONSUME_LUA),
            refund=client.register_script(_REFUND_LUA),
        )
    return _registered_scripts


def consume(key: str, budget: Budget, cost: int = 1) -> BucketDecision | BucketUnavailable:
    """Atomically refill the bucket and take ``cost`` tokens if available."""
    if cost < 1 or cost > budget.burst:
        raise ValueError(f"cost must be between 1 and burst ({budget.burst}), got {cost}")
    consume_script = _scripts().consume
    try:
        allowed, remaining, retry_after_ms, reset_ms = consume_script(
            keys=[key],
            args=[budget.burst, budget.refill_per_second, cost, int(time.time() * 1000)],
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
    refund_script = _scripts().refund
    try:
        return int(refund_script(keys=[key], args=[budget.burst, cost]))
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


def TEST_reset_scripts() -> None:
    """Drop cached script bindings so tests that swap the redis client re-register."""
    global _registered_scripts
    _registered_scripts = None
