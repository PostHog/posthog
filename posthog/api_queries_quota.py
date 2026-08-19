"""Per-organization monthly counter of chargeable API query bytes read.

The product-owned metering for the free-tier API queries quota: incremented from the
ClickHouse client for chargeable queries, read by the query runner's quota check. Kept
dependency-light (Redis only) so both layers can import it without cycles.
"""

from datetime import UTC, datetime

from dateutil.relativedelta import relativedelta
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

COUNTER_KEY_PREFIX = "@posthog/api-queries-bytes/"
# Keys are month-scoped; TTL only has to outlive the month it closes over.
COUNTER_TTL_SECONDS = 63 * 24 * 3600

API_QUERIES_QUOTA_ERRORS_COUNTER = Counter(
    "posthog_api_queries_quota_errors_total",
    "Errors swallowed by the fail-open api queries quota paths.",
    labelnames=["op"],
)


def _counter_key(org_id: str, now: datetime) -> str:
    return f"{COUNTER_KEY_PREFIX}{org_id}/{now.strftime('%Y%m')}"


def increment_api_queries_bytes(org_id: str, bytes_read: int) -> None:
    if not bytes_read:
        return
    try:
        key = _counter_key(org_id, datetime.now(UTC))
        pipe = get_client().pipeline(transaction=False)
        pipe.incrby(key, bytes_read)
        pipe.expire(key, COUNTER_TTL_SECONDS)
        pipe.execute()
    except Exception as e:
        API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="increment").inc()
        capture_exception(e)


def get_api_queries_bytes(org_id: str) -> int:
    try:
        value = get_client().get(_counter_key(org_id, datetime.now(UTC)))
        return int(value) if value else 0
    except Exception as e:
        API_QUERIES_QUOTA_ERRORS_COUNTER.labels(op="read").inc()
        capture_exception(e)
        return 0


def next_counter_reset(now: datetime) -> datetime:
    """First instant of the next UTC month, when the counter key rolls over."""
    return datetime(now.year, now.month, 1, tzinfo=UTC) + relativedelta(months=1)
