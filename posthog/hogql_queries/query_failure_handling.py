from datetime import UTC, datetime
from typing import Optional

from rest_framework.exceptions import APIException

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level, get_team_kill_switch_level
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import (
    ClickHouseBytesLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE, Budget, FailureKind, QueryFailureRecord

# The app-side mapping between failure kinds and exception classes; the breaker itself only
# knows kinds. The stored failure details get shown to users, including on public share links,
# so every class here must only ever carry user-safe detail copy.
FAILURE_KIND_EXCEPTIONS: dict[FailureKind, type[APIException]] = {
    "memory_limit": ClickHouseQueryMemoryLimitExceeded,
    "timeout": ClickHouseQueryTimeOut,
    "too_slow": ClickHouseEstimatedQueryExecutionTimeTooLong,
    "query_size": ClickHouseQuerySizeExceeded,
    "too_many_bytes": ClickHouseBytesLimitExceeded,
}


# User-caused query failures: the query is too big, too slow, or scans too much. Both the fresh
# classes raised when a query hits ClickHouse and the classes build_failure_exception replays from
# cache. The user fixes these by narrowing the query, so they are not defects.
_USER_QUERY_ERROR_CLASSES: tuple[type[Exception], ...] = (
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQuerySizeExceeded,
    ClickHouseBytesLimitExceeded,
    CHQueryErrorTooManyBytes,
)

# The Temporal interceptor sees these wrapped as an ApplicationError whose `type` is the original
# class name, so it matches by name rather than isinstance.
USER_QUERY_ERROR_TYPE_NAMES: frozenset[str] = frozenset(cls.__name__ for cls in _USER_QUERY_ERROR_CLASSES)


def is_expected_user_query_error(error: Exception) -> bool:
    """True for user-caused query failures and for any failure the breaker replayed from cache.
    Capture sites skip error tracking for these — they are the user's to fix, not defects."""
    if getattr(error, "served_from_query_failure_cache", False):
        return True
    if isinstance(error, ClickHouseQueryMemoryLimitExceeded) and not error.is_per_query_limit:
        # Cluster or user-wide memory pressure is transient infra, not the user's query.
        return False
    return isinstance(error, _USER_QUERY_ERROR_CLASSES)


def classify_failure(error: Exception, team_id: Optional[int] = None) -> Optional[FailureKind]:
    """Return the failure kind for errors that will repeat on retry, None for everything else."""
    if isinstance(error, ClickHouseQueryMemoryLimitExceeded):
        return "memory_limit" if error.is_per_query_limit else None
    if isinstance(error, ClickHouseQueryTimeOut):
        return "timeout"
    if isinstance(error, ClickHouseEstimatedQueryExecutionTimeTooLong):
        return "too_slow"
    if isinstance(error, ClickHouseQuerySizeExceeded):
        return "query_size"
    if isinstance(error, CHQueryErrorTooManyBytes):
        # Under an active kill switch (global or team-scoped) the bytes cap is temporary
        # cluster protection, so the failure says nothing about the query once it lifts.
        if get_kill_switch_level() != KillSwitchLevel.OFF:
            return None
        if team_id is not None and get_team_kill_switch_level(team_id) != KillSwitchLevel.OFF:
            return None
        return "too_many_bytes"
    return None


def budget_for_limit_context(limit_context: Optional[LimitContext]) -> Budget:
    """Interactive requests get 60s of ClickHouse execution time while async workers and other
    elevated contexts get 10x that, so a failure only proves anything about the budget it ran
    under."""
    return BUDGET_INTERACTIVE if limit_context in (None, LimitContext.QUERY) else BUDGET_EXTENDED


def _approximate_wait(open_until: datetime) -> str:
    minutes = max(1, round((open_until - datetime.now(UTC)).total_seconds() / 60))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = max(1, round(minutes / 60))
    return f"{hours} hour{'s' if hours != 1 else ''}"


def build_failure_exception(record: QueryFailureRecord) -> APIException:
    """Rebuild the remembered failure with its original exception class, so status codes and
    frontend error handling stay identical to a fresh failure. The original message leads and
    the breaker context follows it."""
    sentences = [record.detail]
    if record.consecutive_failures == 1:
        sentences.append("This query failed in a way that will repeat, so it was not run again.")
    else:
        sentences.append(
            f"This query failed the same way {record.consecutive_failures} times in a row, so it was not run again."
        )
    if record.open_until is not None:
        sentences.append(f"It can run again in about {_approximate_wait(record.open_until)}.")
    error = FAILURE_KIND_EXCEPTIONS[record.kind](detail=" ".join(sentences))
    error.served_from_query_failure_cache = True  # type: ignore[attr-defined]
    return error
