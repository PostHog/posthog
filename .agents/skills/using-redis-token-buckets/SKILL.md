---
name: using-redis-token-buckets
description: 'Use when adding a bucket-like rate limit backed by Redis: a per-caller budget with burst capacity and continuous refill, a refund path for requests that did no work, or a limit whose Retry-After must be a real wait rather than a window edge. `posthog/token_bucket.py` provides an atomic Lua token bucket (`consume`, `refund`, `peek`) over `posthog.redis.get_client()`. Choose it over DRF `SimpleRateThrottle`/fixed-window cache counters when boundary bursts, top-of-window lockouts, or charge-then-refund semantics matter. Trigger terms: token bucket, rate limit, burst, refill, quota, Retry-After, fixed window, throttle.'
---

# Using Redis token buckets

`posthog/token_bucket.py` is the repo's primitive for bucket-like limits in Redis. A bucket holds up to `burst` tokens and refills continuously at `per_hour / 3600` tokens per second. Every operation is atomic (a server-side Lua script), so concurrent web workers cannot double-spend a token.

## Use this skill when

- Adding a rate limit where callers legitimately burst but must be capped on sustained rate
- A limit needs a **refund** path: charge on entry, give the token back when the request provably did no work
- `Retry-After` must be the real per-caller wait for the next token, not "seconds until the top of the hour"
- Replacing a fixed-window cache counter that suffers 2x boundary bursts or full-window lockouts
- Exposing `RateLimit-Limit/Remaining/Reset` headers or a quota introspection endpoint (use `peek`)

## When NOT to use it

- **Per-IP or per-user request throttling on ordinary DRF endpoints**: subclass the existing throttles in `posthog/rate_limit.py` (`IPThrottle`, `UserRateThrottle`, `PersonalApiKeyRateThrottle`). They integrate with DRF's lifecycle and the `RATE_LIMIT_ENABLED` instance setting.
- **Outbound third-party API calls**: use `posthog/egress/` and its `limits`-library sliding-window limiter (`posthog/egress/limiter/`), which carries priorities and degraded fallbacks.
- **Hard quotas that must survive a Redis flush**: a bucket is best-effort (eviction or failover hands the caller a fresh budget). Pair it with a durable Postgres count for the few operations where that matters, and treat the bucket as the fast path.
- **Concurrency caps** (how many at once, not how often): see the sorted-set gate in `posthog/clickhouse/client/limit.py`.

## `limits` (vendored library) vs this module

The repo also vendors the [`limits`](https://limits.readthedocs.io/) library (used by `posthog/egress/limiter/backends.py`). Pick by the semantics you need, not by familiarity:

- **Use `limits`** when a plain window answers the question "no more than N per window" and nothing ever needs to be un-counted. Its `MovingWindowRateLimiter`/`SlidingWindowCounterRateLimiter` strategies avoid fixed-window boundary bursts, its `RedisStorage` runs its own Lua so hits are atomic, and `test()`/`get_window_stats()` cover peeking and remaining/reset. For outbound third-party calls specifically, don't use it directly; go through `posthog/egress/`, which wraps it with priorities and a degraded in-memory fallback.
- **Use this module** when you need what `limits` cannot express: a token bucket (independent burst capacity and refill rate), a **refund** path (its API is `hit`/`test`/`get_window_stats`/`clear`; there is no way to give a hit back), a `Retry-After` that is the wait for the next token rather than the window edge, or variable per-request cost.

A custom script is the de-facto token-bucket implementation on stock Redis (no native rate-limit command; the redis-cell module is not deployed), and `limits` runs its own Lua anyway, so neither choice avoids Lua.

## The API

```python
from posthog.token_bucket import Budget, BucketDecision, BucketUnavailable, consume, peek, refund

BUDGET = Budget(burst=30, per_hour=120)  # capacity 30, refills one token every 30s

decision = consume(f"myfeature_rate:{team_id}", BUDGET)
match decision:
    case BucketUnavailable():
        ...  # Redis can't answer: usually fail open; fall through to a durable check if you have one
    case BucketDecision(allowed=False):
        raise Throttled(wait=decision.retry_after)  # whole seconds, safe for a Retry-After header
    case BucketDecision():
        ...  # proceed; decision.remaining / .limit / .reset back RateLimit-* headers

# The request turned out to do no work (validation error, capability refusal):
refund(f"myfeature_rate:{team_id}", BUDGET)

# Introspection without charging (headers on reads, a /limits endpoint):
peek(f"myfeature_rate:{team_id}", BUDGET)
```

Semantics worth knowing:

- `consume` charges and answers in one atomic step. `cost` above `burst` is a programmer error (`ValueError`), not a denial.
- `refund` is capped at capacity and treats a missing key as an already-full bucket. Refund only what you charged; refunding on outcomes the caller controls (e.g. their own 4xxs they can trigger for free) is fine, refunding on outcomes an attacker controls to spin the bucket is not.
- `peek` is a plain read plus local refill math, so it can lose a sub-second race to a concurrent charge. Never gate anything on `peek`; gate on `consume`.
- Keys are fully caller-constructed. Prefix them (`<feature>_rate:`), include every identity the budget is scoped to, and never include secrets. The bucket self-expires once it would be full again, so idle keys clean themselves up.
- Nothing raises on Redis failure: every operation returns `BucketUnavailable` and the **caller** decides fail-open vs fall-through. Do not swallow it silently; log or count it so an outage is visible.

## Reference consumer

The agentic provisioning rate limits (`ee/api/agentic_provisioning/ratelimits.py`) are the canonical consumer: per-partner budgets declared on handlers with `@rate_limited`, tier multipliers, refund-on-no-work in `handle_exception`, `RateLimit-*` headers from the decision, and Prometheus counters around every outcome. Read it before building a second rate-limit layer on top of the bucket.

## Testing

Under `settings.TEST`, `posthog.redis.get_client()` returns fakeredis, which executes the Lua scripts (via lupa). Control time with `freeze_time` (the script's clock is passed in from Python), reset between tests with `posthog.redis.TEST_clear_clients()` + `posthog.token_bucket.TEST_reset_scripts()`, and see `posthog/test/test_token_bucket.py` for the pattern.
