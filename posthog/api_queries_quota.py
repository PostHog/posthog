"""Per-organization monthly counter of chargeable API query bytes read.

The product-owned metering for the free-tier API queries quota: incremented from the
ClickHouse client for chargeable queries, read by the query runner's quota check. Kept
dependency-light (Redis only) so both layers can import it without cycles.
"""

from datetime import UTC, datetime

from posthog.redis import get_client

COUNTER_KEY_PREFIX = "@posthog/api-queries-bytes/"
# Keys are month-scoped; TTL only has to outlive the month it closes over.
COUNTER_TTL_SECONDS = 63 * 24 * 3600


def _counter_key(org_id: str, now: datetime) -> str:
    return f"{COUNTER_KEY_PREFIX}{org_id}/{now.strftime('%Y%m')}"


def increment_api_queries_bytes(org_id: str, bytes_read: int) -> None:
    """Fail-open INCRBY; an error undercounts one query, never breaks it."""
    if not bytes_read:
        return
    try:
        key = _counter_key(org_id, datetime.now(UTC))
        pipe = get_client().pipeline(transaction=False)
        pipe.incrby(key, bytes_read)
        pipe.expire(key, COUNTER_TTL_SECONDS)
        pipe.execute()
    except Exception:
        pass


def get_api_queries_bytes(org_id: str) -> int:
    """Bytes read by the org's chargeable queries this UTC month. Fail-open to 0."""
    try:
        value = get_client().get(_counter_key(org_id, datetime.now(UTC)))
        return int(value) if value else 0
    except Exception:
        return 0


def next_counter_reset(now: datetime) -> datetime:
    """First instant of the next UTC month, when the counter key rolls over."""
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return datetime(now.year, now.month + 1, 1, tzinfo=UTC)
