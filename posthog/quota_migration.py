from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import field
from functools import partial
from math import inf
from time import monotonic, sleep, time

from django.conf import settings
from django.utils import timezone

import structlog
from prometheus_client import Counter, Gauge
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    RedisClusterException,
    TimeoutError as RedisTimeoutError,
)

from posthog.dataclasses import frozen
from posthog.quota_redis import QuotaRedisClient, get_secondary_quota_redis_client, reconcile_quota_set
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

QUOTA_SECONDARY_OPERATIONS = Counter(
    "billing_quota_secondary_operations_total", "Optional quota Redis operations", ["operation", "result"]
)
SECONDARY_RETRY_DELAY_SECONDS = 30
# Covers the optional store's snapshot and reconcile in one quota run, not the time between them.
QUOTA_SECONDARY_RUN_BUDGET_SECONDS = 300.0
QUOTA_READ_PAGE_SIZE = 5_000
QUOTA_READ_RETRY_DELAYS_SECONDS = (1.0, 2.0)
# A cluster client that times out drops its only seed node, so redis-py raises RedisClusterException, not the timeout.
_QUOTA_READ_RETRY_ERRORS = (RedisClusterException, RedisConnectionError, RedisTimeoutError)
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


def _read_retries() -> Iterator[tuple[int, float]]:
    return enumerate(QUOTA_READ_RETRY_DELAYS_SECONDS, start=1)


@frozen
class _QuotaReadPage:
    client: QuotaRedisClient
    next_cursor: int
    members: list[tuple[bytes, float]]


def _read_quota_page(
    client: QuotaRedisClient, key: str, cursor: int, deadline: float, retries: Iterator[tuple[int, float]]
) -> _QuotaReadPage:
    try:
        next_cursor, page = client.zscan(key, cursor, count=QUOTA_READ_PAGE_SIZE)
        return _QuotaReadPage(client=client, next_cursor=next_cursor, members=page)
    except _QUOTA_READ_RETRY_ERRORS as error:
        failure = error
    for attempt, delay in retries:
        if monotonic() + delay >= deadline:
            break
        logger.warning("quota_secondary_read_retry", key=key, attempt=attempt, error_type=type(failure).__name__)
        sleep(delay)
        try:
            retry_client = get_secondary_quota_redis_client(maintenance=True)
            if retry_client is None:
                break
            next_cursor, page = retry_client.zscan(key, cursor, count=QUOTA_READ_PAGE_SIZE)
            return _QuotaReadPage(client=retry_client, next_cursor=next_cursor, members=page)
        except _QUOTA_READ_RETRY_ERRORS as error:
            failure = error
    raise failure


def _read_quota_set(
    client: QuotaRedisClient, key: str, retries: Iterator[tuple[int, float]], deadline: float = inf
) -> tuple[QuotaRedisClient, dict[bytes, float]]:
    # Concurrent web writes shift ZRANGE ranks between pages. ZSCAN returns every member that stays
    # present for the whole scan and can return a member twice, so the dict keeps one score per member.
    scores: dict[bytes, float] = {}
    cursor = 0
    while True:
        if monotonic() >= deadline:
            raise TimeoutError("Quota Redis run budget exceeded")
        page = _read_quota_page(client, key, cursor, deadline, retries)
        client = page.client
        cursor = page.next_cursor
        scores.update(page.members)
        if cursor == 0:
            return client, scores


@frozen
class QuotaReconciliationSnapshots:
    shared: Mapping[str, Sequence[str]] = field(repr=False)
    secondary: Mapping[str, Sequence[str]] | None = field(repr=False)
    secondary_budget_seconds_left: float

    def without_tokens(self, protected_tokens: set[str]) -> "QuotaReconciliationSnapshots":
        def exclude(snapshot: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
            return {
                key: [token for token in tokens if token not in protected_tokens] for key, tokens in snapshot.items()
            }

        return QuotaReconciliationSnapshots(
            shared=exclude(self.shared),
            secondary=None if self.secondary is None else exclude(self.secondary),
            secondary_budget_seconds_left=self.secondary_budget_seconds_left,
        )


def snapshot_quota_stores(selected: Mapping[str, Sequence[str]]) -> QuotaReconciliationSnapshots:
    """Every store removes only tokens it contained before this quota run's decisions."""
    now = timezone.now().timestamp()
    deadline = monotonic() + QUOTA_SECONDARY_RUN_BUDGET_SECONDS
    # One retry allowance for all keys, because the snapshot delays the shared writes that follow it.
    retries = _read_retries()

    def read(client: QuotaRedisClient) -> dict[str, list[str]]:
        snapshot: dict[str, list[str]] = {}
        for key in selected:
            client, scores = _read_quota_set(client, key, retries, deadline)
            snapshot[key] = [token.decode("utf-8") for token, score in scores.items() if score >= now]
        return snapshot

    return QuotaReconciliationSnapshots(
        shared=selected,
        secondary=run_secondary_quota_operation("snapshot", read, resource="snapshot", maintenance=True),
        secondary_budget_seconds_left=max(deadline - monotonic(), 0.0),
    )


def reconcile_secondary_quota_sets(
    store_snapshots: QuotaReconciliationSnapshots, tokens_by_key: Mapping[str, Mapping[str, int]]
) -> None:
    """Writes a quota run's verdicts to the optional store, within what is left of the run budget."""
    secondary_snapshot = store_snapshots.secondary
    if secondary_snapshot is None:
        return
    now = timezone.now().timestamp()
    run_deadline = monotonic() + store_snapshots.secondary_budget_seconds_left
    skipped_sets = 0
    for key, tokens in tokens_by_key.items():
        if monotonic() >= run_deadline:
            skipped_sets += 1
            QUOTA_SECONDARY_OPERATIONS.labels(operation="reconcile", result="run_budget_exceeded").inc()
            continue
        run_secondary_quota_operation(
            "reconcile",
            partial(
                reconcile_quota_set,
                key=key,
                snapshot_tokens=secondary_snapshot[key],
                tokens=tokens,
                now=now,
                run_deadline=run_deadline,
            ),
            resource=key,
            maintenance=True,
        )
    if skipped_sets:
        logger.warning("quota_secondary_run_budget_exceeded", skipped_sets=skipped_sets)


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
        configured_secondary = get_secondary_quota_redis_client(maintenance=True)
        if configured_secondary is None:
            return False
        secondary = configured_secondary
        retries = _read_retries()

        def differences(key: str) -> dict[bytes, _QuotaScoreDifference]:
            nonlocal secondary
            shared_scores = dict(shared.zrange(key, 0, -1, withscores=True))
            secondary, secondary_scores = _read_quota_set(secondary, key, retries)
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
