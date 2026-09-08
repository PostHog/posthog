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
"""

import math
import time
from contextvars import ContextVar
from typing import Any, Optional

from django.conf import settings

from prometheus_client import Counter

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


# KEYS[1] bucket, ARGV[1] now in seconds, ARGV[2] bytes per hour, ARGV[3] capacity, ARGV[4] ttl.
# A missing bucket starts full. The floor is one hour of refill. Capacity and floor are stored so
# a debit that arrives before any read (a chargeable query that did not go through the query
# runner) can use them.
_REFILL_AND_READ = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local refilled_at = tonumber(redis.call('HGET', KEYS[1], 'refilled_at'))
local now = tonumber(ARGV[1])
local floor = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
if tokens == nil then tokens = capacity end
if refilled_at == nil then refilled_at = now end
tokens = math.min(capacity, tokens + math.max(0, now - refilled_at) / 3600 * floor)
tokens = math.max(tokens, -floor)
redis.call('HSET', KEYS[1], 'tokens', tokens, 'refilled_at', now, 'capacity', capacity, 'floor', floor)
redis.call('EXPIRE', KEYS[1], ARGV[4])
return tostring(tokens)
"""

# KEYS[1] bucket, ARGV[1] bytes, ARGV[2] fallback capacity, ARGV[3] fallback floor, ARGV[4] ttl.
_DEBIT = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local capacity = tonumber(redis.call('HGET', KEYS[1], 'capacity'))
local floor = tonumber(redis.call('HGET', KEYS[1], 'floor'))
if capacity == nil then capacity = tonumber(ARGV[2]) end
if floor == nil then floor = tonumber(ARGV[3]) end
if tokens == nil then tokens = capacity end
tokens = math.max(tokens - tonumber(ARGV[1]), -floor)
redis.call('HSET', KEYS[1], 'tokens', tokens, 'capacity', capacity, 'floor', floor)
redis.call('EXPIRE', KEYS[1], ARGV[4])
return tostring(tokens)
"""


def refill_and_read(team_id: str, spec: BudgetSpec, now: Optional[float] = None) -> Optional[float]:
    try:
        result = get_client().eval(
            _REFILL_AND_READ,
            1,
            _bucket_key(team_id),
            now if now is not None else time.time(),
            spec.bytes_per_hour,
            spec.capacity_bytes,
            BUDGET_TTL_SECONDS,
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
        result = get_client().eval(
            _DEBIT,
            1,
            _bucket_key(team_id),
            int(bytes_read),
            free.capacity_bytes,
            free.bytes_per_hour,
            BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="debit").inc()
        capture_exception(e)
        return None


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
