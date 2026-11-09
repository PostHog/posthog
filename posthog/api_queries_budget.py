"""Hourly read budget for API key queries.

Each team has a token bucket in Redis measured in bytes read. The rate starts from the team's
organization, since the subscription belongs to the organization: teams of a paying organization
refill API_QUERIES_BUDGET_PAID_MULTIPLIER times faster. It then grows with the events the team
ingested in the last year (TeamEventVolume, refreshed nightly), up to
API_QUERIES_BUDGET_MAX_BYTES_PER_HOUR. The ClickHouse client debits what every
budgeted query read after it runs (posthog/clickhouse/client/execute.py) and the query runner
reads the balance before admitting one. Refill is lazy: the balance is only brought up to date
when it is read, so a debit never needs to know the team's rate. The balance floors at minus one
hour of refill, so the query that crosses the line can never lock a team out for longer than an
hour. Everything fails open.

A second bucket per organization counts the CPU time of personal API key queries outside Endpoints,
in CPU microseconds, at a flat API_QUERIES_CPU_BUDGET_SECONDS_PER_HOUR. sync_execute reads it before
each such query and debits it after. It only observes: an exhausted bucket is counted and reported,
and the query still runs.

Exports:
* BudgetSpec, budget_spec_for, budget_enabled
* refill_and_read, debit, seconds_until_positive
* QueryCost, reset_request_query_cost, record_request_query_cost, get_request_query_cost
* claim_limited_event
* cpu_budget_enabled, CpuBudgetStatus, org_cpu_budget_status, debit_org_cpu, observe_org_cpu_budget
"""

import math
import time
from contextvars import ContextVar
from typing import Any, Optional

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_background_capture
from posthog.redis import get_client
from posthog.utils import get_instance_region

BUDGET_KEY_PREFIX = "@posthog/api-queries-budget/"
# A bucket nobody touches for a week is rebuilt full on the next read, so the key can expire.
BUDGET_TTL_SECONDS = 7 * 24 * 3600
# Budget checks run on request paths and fail open, so they must not inherit the longer timeout
# used by Redis callers that can safely wait for blocking commands.
BUDGET_REDIS_TIMEOUT_SECONDS = 1.0

API_QUERIES_BUDGET_ERRORS_COUNTER = Counter(
    "posthog_api_queries_budget_errors_total",
    "Errors swallowed by the fail-open api queries budget paths.",
    labelnames=["op"],
)

API_QUERIES_CPU_BUDGET_LIMITED_COUNTER = Counter(
    "posthog_api_queries_cpu_budget_limited_total",
    "Personal API key queries started while their organization's hourly CPU budget was exhausted.",
    labelnames=["outcome"],  # observed
)

API_QUERIES_CPU_BUDGET_UNMETERED_COUNTER = Counter(
    "posthog_api_queries_cpu_budget_unmetered_total",
    "Personal API key queries that ran on a client that reports no CPU, such as the HTTP client.",
)

LIMITED_EVENT = "api queries budget limited"

# Named so posthog/settings/logs.py can opt it into INFO: the posthoganalytics SDK clamps the
# "posthog" logger tree to WARNING, which would drop the budget line under __name__.
budget_logger = structlog.get_logger("posthog.api_queries_budget")


@frozen
class BudgetSpec:
    bytes_per_hour: float
    capacity_bytes: float


@frozen
class CpuBudgetStatus:
    remaining_cpu_us: float
    cpu_us_per_hour: float
    retry_after_seconds: int


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


def budget_spec_for(organization: Any, events_last_year: Optional[int] = None) -> BudgetSpec:
    bytes_per_hour = float(settings.API_QUERIES_BUDGET_FREE_BYTES_PER_HOUR)
    # NULL means the subscription state was never synced, and an organization is not refused
    # on a number we do not have.
    if organization.has_active_subscription is not False:
        bytes_per_hour *= float(settings.API_QUERIES_BUDGET_PAID_MULTIPLIER)
    scaled = (events_last_year or 0) * float(settings.API_QUERIES_BUDGET_BYTES_PER_EVENT_PER_HOUR)
    return _spec(min(max(bytes_per_hour, scaled), float(settings.API_QUERIES_BUDGET_MAX_BYTES_PER_HOUR)))


def cpu_budget_enabled() -> bool:
    return float(settings.API_QUERIES_CPU_BUDGET_SECONDS_PER_HOUR) > 0


def _cpu_us_per_hour() -> float:
    return float(settings.API_QUERIES_CPU_BUDGET_SECONDS_PER_HOUR) * 1_000_000


def _cpu_capacity_us() -> float:
    return _cpu_us_per_hour() * float(settings.API_QUERIES_BUDGET_CAPACITY_HOURS)


def _bucket_key(team_id: str) -> str:
    return f"{BUDGET_KEY_PREFIX}team/{team_id}"


def _cpu_bucket_key(org_id: str) -> str:
    return f"{BUDGET_KEY_PREFIX}cpu/org/{org_id}"


def _budget_redis_client():
    return get_client(
        socket_timeout=BUDGET_REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=BUDGET_REDIS_TIMEOUT_SECONDS,
    )


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


def _refill_and_read(
    key: str, per_hour: float, capacity: float, now: Optional[float], error_op: str
) -> Optional[float]:
    try:
        result = _budget_redis_client().eval(
            _REFILL_AND_READ,
            1,
            key,
            now if now is not None else time.time(),
            per_hour,
            capacity,
            BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op=error_op).inc()
        capture_exception(e)
        return None


def _debit(key: str, amount: int, capacity: float, per_hour: float, error_op: str) -> Optional[float]:
    try:
        result = _budget_redis_client().eval(
            _DEBIT,
            1,
            key,
            int(amount),
            capacity,
            per_hour,
            BUDGET_TTL_SECONDS,
        )
        return float(result)
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op=error_op).inc()
        capture_exception(e)
        return None


def refill_and_read(team_id: str, spec: BudgetSpec, now: Optional[float] = None) -> Optional[float]:
    return _refill_and_read(_bucket_key(team_id), spec.bytes_per_hour, spec.capacity_bytes, now, "read")


def debit(team_id: str, bytes_read: int) -> Optional[float]:
    """Take the bytes off the team's bucket. Returns the remaining balance, or None when the budget
    is disabled or Redis failed."""
    if not budget_enabled() or bytes_read <= 0:
        return None
    free = _free_spec()
    return _debit(_bucket_key(team_id), bytes_read, free.capacity_bytes, free.bytes_per_hour, "debit")


def debit_org_cpu(org_id: str, cpu_us: int) -> Optional[float]:
    """Take the CPU microseconds off the organization's bucket. Returns the remaining balance, or None
    when the CPU budget is disabled or Redis failed."""
    if not cpu_budget_enabled() or cpu_us <= 0:
        return None
    return _debit(_cpu_bucket_key(org_id), cpu_us, _cpu_capacity_us(), _cpu_us_per_hour(), "cpu_debit")


def org_cpu_budget_status(org_id: str, now: Optional[float] = None) -> Optional[CpuBudgetStatus]:
    if not cpu_budget_enabled():
        return None
    per_hour = _cpu_us_per_hour()
    remaining = _refill_and_read(_cpu_bucket_key(org_id), per_hour, _cpu_capacity_us(), now, "cpu_read")
    if remaining is None:
        return None
    return CpuBudgetStatus(
        remaining_cpu_us=remaining,
        cpu_us_per_hour=per_hour,
        retry_after_seconds=_seconds_until_positive(remaining, per_hour),
    )


LIMITED_EVENT_INTERVAL_SECONDS = 3600


def _claim_limited_event(key: str, error_op: str) -> bool:
    try:
        return bool(_budget_redis_client().set(key, "1", nx=True, ex=LIMITED_EVENT_INTERVAL_SECONDS))
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op=error_op).inc()
        capture_exception(e)
        return False


def claim_limited_event(team_id: str) -> bool:
    return _claim_limited_event(f"{BUDGET_KEY_PREFIX}limited-event/{team_id}", "limited_event")


def _claim_cpu_limited_event(org_id: str) -> bool:
    return _claim_limited_event(f"{BUDGET_KEY_PREFIX}limited-event/cpu/org/{org_id}", "cpu_limited_event")


def _seconds_until_positive(remaining: float, per_hour: float) -> int:
    if remaining > 0:
        return 0
    if per_hour <= 0:
        return 1
    # A zero balance is still exhausted, and DRF only sends Retry-After for a positive wait.
    return max(1, math.ceil(-remaining / (per_hour / 3600.0)))


def seconds_until_positive(remaining: float, spec: BudgetSpec) -> int:
    return _seconds_until_positive(remaining, spec.bytes_per_hour)


def observe_org_cpu_budget(org_id: str, team_id: Optional[int], product: Optional[str]) -> None:
    """Count and report a personal API key query whose organization has no CPU budget left.

    Never refuses and never raises, so a Redis or analytics failure cannot fail the query.
    """
    try:
        status = org_cpu_budget_status(org_id)
        if status is None or status.remaining_cpu_us > 0:
            return
        outcome = "observed"
        API_QUERIES_CPU_BUDGET_LIMITED_COUNTER.labels(outcome=outcome).inc()
        budget_logger.info(
            "api_queries_budget_limited",
            budget="cpu",
            organization_id=org_id,
            team_id=team_id,
            remaining_cpu_seconds=status.remaining_cpu_us / 1_000_000,
            cpu_seconds_per_hour=status.cpu_us_per_hour / 1_000_000,
            retry_after_seconds=status.retry_after_seconds,
            outcome=outcome,
        )
        if _claim_cpu_limited_event(org_id):
            ph_background_capture(region=get_instance_region() or "US")(
                distinct_id=org_id,
                event=LIMITED_EVENT,
                properties={
                    "budget": "cpu",
                    "outcome": outcome,
                    "team_id": team_id,
                    "cpu_seconds_per_hour": status.cpu_us_per_hour / 1_000_000,
                    "remaining_cpu_seconds": status.remaining_cpu_us / 1_000_000,
                    "retry_after_seconds": status.retry_after_seconds,
                    "access_method": "personal_api_key",
                    "product": str(product) if product else None,
                },
                groups={"instance": settings.SITE_URL, "organization": org_id},
            )
    except Exception as e:
        API_QUERIES_BUDGET_ERRORS_COUNTER.labels(op="cpu_check").inc()
        capture_exception(e)


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
