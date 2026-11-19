from collections.abc import Callable, Mapping, Sequence
from dataclasses import field
from time import monotonic, sleep, time

from django.conf import settings
from django.utils import timezone

import structlog
from prometheus_client import Counter, Gauge

from posthog.dataclasses import frozen
from posthog.quota_redis import QuotaRedisClient, get_secondary_quota_redis_client
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

QUOTA_SECONDARY_OPERATIONS = Counter(
    "billing_quota_secondary_operations_total", "Optional quota Redis operations", ["operation", "result"]
)
SECONDARY_RETRY_DELAY_SECONDS = 30
_retry_after: dict[str, float] = {}

QUOTA_MIGRATION_ENABLED = Gauge(
    "billing_quota_migration_enabled",
    "Whether this deployment has an optional quota Redis configured",
    multiprocess_mode="livemax",
)
QUOTA_MIGRATION_STARTED = Gauge(
    "billing_quota_migration_started_timestamp_seconds",
    "When this deployment began waiting for its first quota comparison",
    multiprocess_mode="livemax",
)

QUOTA_COMPARE_MISMATCHES = Gauge(
    "billing_quota_compare_mismatches",
    "Quota members with an unchanged difference after rechecking",
    ["key"],
    multiprocess_mode="mostrecent",
)
QUOTA_COMPARE_LAST_SUCCESS = Gauge(
    "billing_quota_compare_last_success_timestamp_seconds",
    "Last completed quota Redis comparison",
    multiprocess_mode="max",
)
QUOTA_COMPARE_FAILURES = Counter("billing_quota_compare_failures_total", "Failed quota Redis comparisons")


def run_secondary_quota_operation[T](
    operation: str, callback: Callable[[QuotaRedisClient], T], *, resource: str, maintenance: bool = False
) -> T | None:
    """Best-effort migration work must never fail a successful shared Redis write."""
    url = settings.QUOTA_LIMITING_REDIS_URL
    if not url:
        return None
    if monotonic() < _retry_after.get(url, 0):
        QUOTA_SECONDARY_OPERATIONS.labels(operation=operation, result="cooldown").inc()
        return None
    try:
        client = get_secondary_quota_redis_client(maintenance=maintenance)
        if client is None:
            return None
        result = callback(client)
    except Exception as error:
        # Include configuration/discovery failures: even an invalid optional URL must
        # leave shared Redis authoritative. A dead store costs one timeout per cooldown.
        _retry_after[url] = monotonic() + SECONDARY_RETRY_DELAY_SECONDS
        QUOTA_SECONDARY_OPERATIONS.labels(operation=operation, result="failure").inc()
        logger.warning(
            "quota_secondary_operation_failed", operation=operation, resource=resource, error_type=type(error).__name__
        )
        return None
    QUOTA_SECONDARY_OPERATIONS.labels(operation=operation, result="success").inc()
    return result


@frozen
class QuotaReconciliationSnapshots:
    shared: Mapping[str, Sequence[str]] = field(repr=False)
    secondary: Mapping[str, Sequence[str]] | None = field(repr=False)

    def without_tokens(self, protected_tokens: set[str]) -> "QuotaReconciliationSnapshots":
        def exclude(snapshot: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
            return {
                key: [token for token in tokens if token not in protected_tokens] for key, tokens in snapshot.items()
            }

        return QuotaReconciliationSnapshots(
            shared=exclude(self.shared), secondary=None if self.secondary is None else exclude(self.secondary)
        )


def snapshot_quota_stores(selected: Mapping[str, Sequence[str]]) -> QuotaReconciliationSnapshots:
    """Every store removes only tokens it contained before this quota run's decisions."""
    now = timezone.now().timestamp()

    def read(client: QuotaRedisClient) -> dict[str, list[str]]:
        return {key: [token.decode("utf-8") for token in client.zrangebyscore(key, now, "+inf")] for key in selected}

    return QuotaReconciliationSnapshots(
        shared=selected,
        secondary=run_secondary_quota_operation("snapshot", read, resource="snapshot", maintenance=True),
    )


@frozen
class _QuotaScoreDifference:
    shared: float | None
    secondary: float | None


def compare_quota_stores(keys: Sequence[str]) -> bool:
    """Compare full membership and scores, excluding differences that change during recheck."""
    if not settings.QUOTA_LIMITING_REDIS_URL:
        return False
    try:
        shared = get_client(settings.REDIS_READER_URL or settings.REDIS_URL)
        secondary = get_secondary_quota_redis_client(maintenance=True)
        if secondary is None:
            return False

        def differences(key: str) -> dict[bytes, _QuotaScoreDifference]:
            shared_scores = dict(shared.zrange(key, 0, -1, withscores=True))
            secondary_scores = dict(secondary.zrange(key, 0, -1, withscores=True))
            return {
                token: _QuotaScoreDifference(shared=shared_scores.get(token), secondary=secondary_scores.get(token))
                for token in shared_scores.keys() | secondary_scores.keys()
                if shared_scores.get(token) != secondary_scores.get(token)
            }

        initial = {key: differences(key) for key in keys}
        counts = dict.fromkeys(keys, 0)
        if any(initial.values()):
            sleep(2)
            for key, first in initial.items():
                if first:
                    second = differences(key)
                    counts[key] = sum(second.get(token) == value for token, value in first.items())
    except Exception as error:
        # Preserve the last result and its timestamp. Missing data cannot establish parity.
        QUOTA_COMPARE_FAILURES.inc()
        logger.warning("quota_comparison_failed", error_type=type(error).__name__)
        return False
    for key, count in counts.items():
        QUOTA_COMPARE_MISMATCHES.labels(key=key).set(count)
    QUOTA_COMPARE_LAST_SUCCESS.set(time())
    return True
