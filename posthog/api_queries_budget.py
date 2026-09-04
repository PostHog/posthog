"""Hourly read budget for API key queries.

Each team has a token bucket in Redis measured in bytes read. The rate comes from
the team's organization, since the subscription belongs to the organization: teams of a paying
organization refill API_QUERIES_BUDGET_PAID_MULTIPLIER times faster. The ClickHouse client debits
what every chargeable query read after it runs (posthog/clickhouse/client/execute.py) and the query
runner reads the balance before admitting one. Refill is lazy: the balance is only brought up to
date when it is read, so a debit never needs to know the team's rate. The balance floors at minus
one capacity, so a burst can never lock a team out for longer than the capacity window. Everything
fails open.

The same debit adds the bytes to a monthly counter per organization, the organization's API read
volume for the month.

Exports:
* BudgetSpec, budget_spec_for, budget_enabled
* refill_and_read, meter_query, seconds_until_positive
* get_api_queries_bytes
* QueryCost, reset_request_query_cost, record_request_query_cost, get_request_query_cost
"""

import math
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

BUDGET_KEY_PREFIX = "@posthog/api-queries-budget/"
# A bucket nobody touches for a week is rebuilt full on the next read, so the key can expire.
BUDGET_TTL_SECONDS = 7 * 24 * 3600

COUNTER_KEY_PREFIX = "@posthog/api-queries-bytes/"
# Keys are month-scoped; TTL only has to outlive the month it closes over.
COUNTER_TTL_SECONDS = 63 * 24 * 3600

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


def budget_enabled() -> bool:
    return float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR) > 0


def budget_spec_for(organization: Any) -> BudgetSpec:
    bytes_per_hour = float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR)
    # NULL means the subscription state was never synced, and an organization is not refused
    # on a number we do not have.
    if organization.has_active_subscription is not False:
        bytes_per_hour *= float(settings.API_QUERIES_BUDGET_PAID_MULTIPLIER)
    return BudgetSpec(
        bytes_per_hour=bytes_per_hour,
        capacity_bytes=bytes_per_hour * float(settings.API_QUERIES_BUDGET_CAPACITY_HOURS),
    )


def _free_capacity_bytes() -> float:
    return float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR) * float(settings.API_QUERIES_BUDGET_CAPACITY_HOURS)


def _bucket_key(team_id: str) -> str:
    return f"{BUDGET_KEY_PREFIX}team/{team_id}"


def _counter_key(org_id: str, now: datetime) -> str:
    return f"{COUNTER_KEY_PREFIX}{org_id}/{now.strftime('%Y%m')}"


# KEYS[1] bucket, ARGV[1] now in seconds, ARGV[2] bytes per second, ARGV[3] capacity, ARGV[4] ttl.
# A missing bucket starts full. The capacity is stored so a debit that arrives before any read
# (a chargeable query that did not go through the query runner) can initialize from it.
_REFILL_AND_READ = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local refilled_at = tonumber(redis.call('HGET', KEYS[1], 'refilled_at'))
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
if tokens == nil then tokens = capacity end
if refilled_at == nil then refilled_at = now end
tokens = math.min(capacity, tokens + math.max(0, now - refilled_at) * rate)
tokens = math.max(tokens, -capacity)
redis.call('HSET', KEYS[1], 'tokens', tokens, 'refilled_at', now, 'capacity', capacity)
redis.call('EXPIRE', KEYS[1], ARGV[4])
return tostring(tokens)
"""

# KEYS[1] bucket, KEYS[2] monthly counter. ARGV[1] bytes, ARGV[2] fallback capacity, ARGV[3] bucket
# ttl, ARGV[4] counter ttl, ARGV[5] 1 to debit the bucket, 0 to only count.
# One script so the client pays a single round trip after every chargeable query.
_METER = """
local bytes = tonumber(ARGV[1])
if bytes > 0 then
  redis.call('INCRBY', KEYS[2], bytes)
  redis.call('EXPIRE', KEYS[2], ARGV[4])
end
if tonumber(ARGV[5]) == 0 then return false end
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local capacity = tonumber(redis.call('HGET', KEYS[1], 'capacity'))
if capacity == nil then capacity = tonumber(ARGV[2]) end
if tokens == nil then tokens = capacity end
tokens = math.max(tokens - bytes, -capacity)
redis.call('HSET', KEYS[1], 'tokens', tokens)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return tostring(tokens)
"""


def refill_and_read(team_id: str, spec: BudgetSpec, now: Optional[float] = None) -> Optional[float]:
    try:
        result = get_client().eval(
            _REFILL_AND_READ,
            1,
            _bucket_key(team_id),
            now if now is not None else time.time(),
            spec.bytes_per_hour / 3600.0,
            spec.capacity_bytes,
            BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read").inc()
        capture_exception(e)
        return None


def meter_query(org_id: str, team_id: Optional[str], bytes_read: int) -> Optional[float]:
    """Add the bytes to the organization's monthly counter and, when the budget is enabled, debit
    them from the team's bucket. Returns the remaining balance, or None when nothing was debited
    or Redis failed."""
    debit_bucket = budget_enabled() and bytes_read > 0 and team_id is not None
    try:
        result = get_client().eval(
            _METER,
            2,
            _bucket_key(team_id or "-"),
            _counter_key(org_id, datetime.now(UTC)),
            int(bytes_read),
            _free_capacity_bytes(),
            BUDGET_TTL_SECONDS,
            COUNTER_TTL_SECONDS,
            1 if debit_bucket else 0,
        )
        return float(result) if result is not None else None
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="meter").inc()
        capture_exception(e)
        return None


def seconds_until_positive(remaining: float, spec: BudgetSpec) -> int:
    if remaining > 0:
        return 0
    if spec.bytes_per_hour <= 0:
        return 1
    # A zero balance is still exhausted, and DRF only sends Retry-After for a positive wait.
    return max(1, math.ceil(-remaining / (spec.bytes_per_hour / 3600.0)))


def get_api_queries_bytes(org_id: str) -> int:
    try:
        value = get_client().get(_counter_key(org_id, datetime.now(UTC)))
        return int(value) if value else 0
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="read").inc()
        capture_exception(e)
        return 0


_request_query_cost: ContextVar[Optional[QueryCost]] = ContextVar("api_queries_request_cost", default=None)


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
