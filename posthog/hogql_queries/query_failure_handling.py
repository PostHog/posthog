from datetime import UTC, datetime
from typing import Optional

from rest_framework.exceptions import APIException

from posthog.hogql.constants import LimitContext

from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.query_cache.failures import SCOPE_ASYNC, SCOPE_SYNC, FailureKind, QueryFailureRecord

# The app-side mapping between failure kinds and exception classes; the breaker itself only
# knows kinds. The stored failure details get shown to users, including on public share links,
# so every class here must only ever carry user-safe detail copy.
FAILURE_KIND_EXCEPTIONS: dict[FailureKind, type[APIException]] = {
    "memory_limit": ClickHouseQueryMemoryLimitExceeded,
    "timeout": ClickHouseQueryTimeOut,
    "too_slow": ClickHouseEstimatedQueryExecutionTimeTooLong,
    "query_size": ClickHouseQuerySizeExceeded,
}


def classify_failure(error: Exception) -> Optional[FailureKind]:
    """Return the failure kind for errors that will repeat on retry, None for everything else."""
    if isinstance(error, ClickHouseQueryMemoryLimitExceeded):
        return "memory_limit" if error.is_per_query_limit else None
    if isinstance(error, ClickHouseQueryTimeOut):
        return "timeout"
    if isinstance(error, ClickHouseEstimatedQueryExecutionTimeTooLong):
        return "too_slow"
    if isinstance(error, ClickHouseQuerySizeExceeded):
        return "query_size"
    return None


def scope_for_limit_context(limit_context: Optional[LimitContext]) -> str:
    """Interactive requests get 60s of ClickHouse execution time while async workers and other
    elevated contexts get 10x that, so a failure only proves anything about the budget it ran
    under."""
    return SCOPE_SYNC if limit_context in (None, LimitContext.QUERY) else SCOPE_ASYNC


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
