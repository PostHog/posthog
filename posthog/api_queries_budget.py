"""Hourly read budget for API key queries.

Each team has a token bucket in Redis measured in bytes read. The rate comes from the team's
organization, since the subscription belongs to the organization: teams of a paying organization
refill API_QUERIES_BUDGET_PAID_MULTIPLIER times faster. The ClickHouse client debits what every
chargeable query read after it runs (posthog/clickhouse/client/execute.py) and the query runner
reads the balance before admitting one. Refill is lazy: the balance is only brought up to date
when it is read, so a debit never needs to know the team's rate. The balance floors at minus one
hour of refill, so the query that crosses the line can never lock a team out for longer than an
hour. Everything fails open.

Exports:
* BudgetSpec, budget_spec_for, budget_enabled
* refill_and_read, debit, seconds_until_positive
* QueryCost, reset_request_query_cost, record_request_query_cost, get_request_query_cost
* claim_limited_event
"""

import math
import time
from contextvars import ContextVar
from typing import Any, Optional

from django.conf import settings

from prometheus_client import Counter
from redis_lua_py import Key, redis, script

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

BUDGET_KEY_PREFIX = "@posthog/api-queries-budget/"
# A bucket nobody touches for a week is rebuilt full on the next read, so the key can expire.
BUDGET_TTL_SECONDS = 7 * 24 * 3600

API_QUERIES_BUDGET_ERRORS_COUNTER = Counter(
    "posthog_api_queries_budget_errors_total",
    "Errors swallowed by the fail-open api queries budget paths.",
    labelnames=["op"],
)


@frozen
class BudgetSpec:
    bytes_per_hour: float
    capacity_bytes: float


@frozen
class QueryCost:
    bytes_read: int
    remaining_bytes: Optional[float]


_request_query_cost: ContextVar[Optional[QueryCost]] = ContextVar("api_queries_request_cost", default=None)


def budget_enabled() -> bool:
    return float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR) > 0


def _spec(bytes_per_hour: float) -> BudgetSpec:
    return BudgetSpec(
        bytes_per_hour=bytes_per_hour,
        capacity_bytes=bytes_per_hour * float(settings.API_QUERIES_BUDGET_CAPACITY_HOURS),
    )


def _free_spec() -> BudgetSpec:
    return _spec(float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR))


def budget_spec_for(organization: Any) -> BudgetSpec:
    bytes_per_hour = float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR)
    # NULL means the subscription state was never synced, and an organization is not refused
    # on a number we do not have.
    if organization.has_active_subscription is not False:
        bytes_per_hour *= float(settings.API_QUERIES_BUDGET_PAID_MULTIPLIER)
    return _spec(bytes_per_hour)


def _bucket_key(team_id: str) -> str:
    return f"{BUDGET_KEY_PREFIX}team/{team_id}"


# A missing bucket starts full. The floor is one hour of refill. Capacity and floor are stored so
# a debit that arrives before any read (a chargeable query that did not go through the query
# runner) can use them. Both return the balance as a string, so it keeps its fraction.
@script
def _refill_and_read_bucket(bucket: Key, now: float, bytes_per_hour: float, capacity: float, ttl: int) -> bytes:
    stored_tokens, stored_refilled_at = redis.hmget(bucket, "tokens", "refilled_at")
    tokens = capacity
    if stored_tokens is not None:
        tokens = float(stored_tokens)
    refilled_at = now
    if stored_refilled_at is not None:
        refilled_at = float(stored_refilled_at)
    tokens = min(capacity, tokens + max(0, now - refilled_at) / 3600 * bytes_per_hour)
    tokens = max(tokens, -bytes_per_hour)
    redis.hset(bucket, "tokens", tokens, "refilled_at", now, "capacity", capacity, "floor", bytes_per_hour)
    redis.expire(bucket, ttl)
    return str(tokens).encode()


@script
def _debit_bucket(bucket: Key, bytes_read: int, fallback_capacity: float, fallback_floor: float, ttl: int) -> bytes:
    stored_tokens, stored_capacity, stored_floor = redis.hmget(bucket, "tokens", "capacity", "floor")
    capacity = fallback_capacity
    if stored_capacity is not None:
        capacity = float(stored_capacity)
    floor = fallback_floor
    if stored_floor is not None:
        floor = float(stored_floor)
    tokens = capacity
    if stored_tokens is not None:
        tokens = float(stored_tokens)
    tokens = max(tokens - bytes_read, -floor)
    redis.hset(bucket, "tokens", tokens, "capacity", capacity, "floor", floor)
    redis.expire(bucket, ttl)
    return str(tokens).encode()


def refill_and_read(team_id: str, spec: BudgetSpec, now: Optional[float] = None) -> Optional[float]:
    try:
        result = _refill_and_read_bucket(
            get_client(),
            bucket=_bucket_key(team_id),
            now=now if now is not None else time.time(),
            bytes_per_hour=spec.bytes_per_hour,
            capacity=spec.capacity_bytes,
            ttl=BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read").inc()
        capture_exception(e)
        return None


def debit(team_id: str, bytes_read: int) -> Optional[float]:
    """Take the bytes off the team's bucket. Returns the remaining balance, or None when the budget
    is disabled or Redis failed."""
    if not budget_enabled() or bytes_read <= 0:
        return None
    free = _free_spec()
    try:
        result = _debit_bucket(
            get_client(),
            bucket=_bucket_key(team_id),
            bytes_read=int(bytes_read),
            fallback_capacity=free.capacity_bytes,
            fallback_floor=free.bytes_per_hour,
            ttl=BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit").inc()
        capture_exception(e)
        return None


LIMITED_EVENT_INTERVAL_SECONDS = 3600


def claim_limited_event(team_id: str) -> bool:
    try:
        return bool(
            get_client().set(
                f"{BUDGET_KEY_PREFIX}limited-event/{team_id}", "1", nx=True, ex=LIMITED_EVENT_INTERVAL_SECONDS
            )
        )
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="limited_event").inc()
        capture_exception(e)
        return False


def seconds_until_positive(remaining: float, spec: BudgetSpec) -> int:
    if remaining > 0:
        return 0
    if spec.bytes_per_hour <= 0:
        return 1
    # A zero balance is still exhausted, and DRF only sends Retry-After for a positive wait.
    return max(1, math.ceil(-remaining / (spec.bytes_per_hour / 3600.0)))


def reset_request_query_cost() -> None:
    _request_query_cost.set(None)


def record_request_query_cost(cost: QueryCost) -> None:
    previous = _request_query_cost.get()
    if previous is None:
        _request_query_cost.set(cost)
        return
    _request_query_cost.set(
        QueryCost(
            bytes_read=previous.bytes_read + cost.bytes_read,
            remaining_bytes=cost.remaining_bytes if cost.remaining_bytes is not None else previous.remaining_bytes,
        )
    )


def get_request_query_cost() -> Optional[QueryCost]:
    return _request_query_cost.get()
