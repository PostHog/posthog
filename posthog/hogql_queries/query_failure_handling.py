from datetime import UTC, datetime
from typing import Optional

from clickhouse_driver.errors import ServerException
from rest_framework.exceptions import APIException

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level, get_team_kill_switch_level
from posthog.errors import CHQueryErrorTooManyBytes, wrap_clickhouse_query_error
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseBytesLimitExceeded,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.query_cache.failures import BUDGET_EXTENDED, BUDGET_INTERACTIVE, Budget, FailureKind, QueryFailureRecord
from posthog.query_cache.single_flight import SharedFailure

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

# The app's ClickHouse limit exceptions a single flight leader can hand to its followers by name.
# Their detail is user-safe copy, and rebuilding one by class keeps its status and machine code.
SHAREABLE_API_FAILURES: dict[str, type[APIException]] = {
    cls.__name__: cls
    for cls in (
        ClickHouseAtCapacity,
        ClickHouseClusterMemoryLimitExceeded,
        ClickHouseEstimatedQueryExecutionTimeTooLong,
        ClickHouseQueryMemoryLimitExceeded,
        ClickHouseQuerySizeExceeded,
        ClickHouseQueryTimeOut,
    )
}


def shareable_failure(error: Exception) -> Optional[SharedFailure]:
    """The part of a leader's failure a follower can rebuild into the same exception.

    A ClickHouse server error rebuilds from its code, because wrap_clickhouse_query_error derives
    the class from the code and message. The app's ClickHouse limit exceptions rebuild by name.
    Anything else (HogQL errors, concurrency and quota limits, transport errors) returns None and
    leaves followers to run the query themselves."""
    if isinstance(error, ServerException) and error.code is not None:
        return SharedFailure(message=str(error.message), code=error.code)
    cls = SHAREABLE_API_FAILURES.get(type(error).__name__)
    if cls is not None and type(error) is cls and isinstance(error, APIException):
        return SharedFailure(
            message=str(error.detail),
            class_name=cls.__name__,
            is_per_query_limit=bool(getattr(error, "is_per_query_limit", False)),
        )
    return None


def rebuild_shared_failure(failure: SharedFailure) -> Optional[Exception]:
    """The leader's exception again, marked as served by the flight. None when the published
    class is unknown to this code version, so the follower runs the query itself instead."""
    error: Exception
    if failure.code is not None:
        error = wrap_clickhouse_query_error(ServerException(failure.message, code=failure.code))
    else:
        cls = SHAREABLE_API_FAILURES.get(failure.class_name or "")
        if cls is None:
            return None
        error = cls(detail=failure.message)
        if failure.is_per_query_limit:
            error.is_per_query_limit = True  # type: ignore[attr-defined]
    error.served_from_query_single_flight = True  # type: ignore[attr-defined]
    return error


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
    if limit_context in (None, LimitContext.QUERY, LimitContext.DATA_CATALOG):
        return BUDGET_INTERACTIVE
    return BUDGET_EXTENDED


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
