from typing import Optional, TypeIs

from clickhouse_driver.errors import ServerException
from rest_framework.exceptions import APIException

from posthog.hogql import errors as hogql_errors
from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, TableAccessDeniedError

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level, get_team_kill_switch_level
from posthog.errors import (
    CHQueryErrorTooManyBytes,
    QueryErrorCategory,
    classify_query_error,
    wrap_clickhouse_query_error,
)
from posthog.exceptions import (
    ClickHouseBytesLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
    QueryRanConcurrently,
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


# Failure categories that repeat for every run of the same query under the same limits. Capacity,
# cancellation, and unclassified errors can pass on the next try, so followers do not inherit them.
SHAREABLE_FAILURE_CATEGORIES = frozenset({QueryErrorCategory.USER_ERROR, QueryErrorCategory.QUERY_PERFORMANCE_ERROR})


def captured_elsewhere(error: BaseException) -> bool:
    """Whether error tracking already holds this failure or has nothing to learn from it: a breaker
    replay, a follower's rebuild of its leader's failure, or a follower whose leader left it nothing
    to serve, which the leader's own capture and the flight metrics account for."""
    return bool(
        isinstance(error, QueryRanConcurrently)
        or getattr(error, "served_from_query_failure_cache", False)
        or getattr(error, "served_from_query_single_flight", False)
    )


def shareable_failure(error: Exception) -> Optional[SharedFailure]:
    """The part of a leader's failure a follower can rebuild into the same exception.

    Only failures that repeat for every run of the query are shared. A ClickHouse server error
    travels by its code; the ClickHouse client raises the app's exception from the server error, so
    the code is found on the exception or behind it. An exposed HogQL error travels by its class.
    The candidate is rebuilt here first and shared only when that gives back the leader's own class
    and message, so nothing the app decided on its own, such as an app-side limit, ever travels."""
    if classify_query_error(error) not in SHAREABLE_FAILURE_CATEGORIES:
        return None
    try:
        candidate = _shared_failure_candidate(error)
        rebuilt = rebuild_shared_failure(candidate) if candidate is not None else None
    except Exception:
        # Sharing is best effort and must never replace the error the leader raises.
        return None
    if candidate is None or rebuilt is None or not same_failure(rebuilt, error):
        return None
    return candidate


def same_failure(rebuilt: Exception, error: Exception) -> bool:
    # The error factory builds a class per call for codes without a dedicated class, so the
    # class name and its bases stand for identity.
    return (
        type(rebuilt).__name__ == type(error).__name__
        and type(rebuilt).__mro__[1:] == type(error).__mro__[1:]
        and str(rebuilt) == str(error)
    )


def _shared_failure_candidate(error: Exception) -> Optional[SharedFailure]:
    cause: Optional[BaseException] = error
    while cause is not None:
        if isinstance(cause, ServerException) and cause.code is not None:
            return SharedFailure(message=str(cause.message), code=cause.code)
        cause = cause.__cause__
    if isinstance(error, ExposedHogQLError) and _is_shareable_hogql_error(type(error)):
        return SharedFailure(
            message=str(error), class_name=type(error).__name__, start=error.start, end=error.end, fix=error.fix
        )
    return None


def _is_shareable_hogql_error(cls: object) -> TypeIs[type[ExposedHogQLError]]:
    # Table access depends on the user, and the users behind one cache key can differ.
    return isinstance(cls, type) and issubclass(cls, ExposedHogQLError) and not issubclass(cls, TableAccessDeniedError)


def rebuild_shared_failure(failure: SharedFailure) -> Optional[Exception]:
    """The leader's exception again, marked as served by the flight. None when this code version
    cannot rebuild it, in which case the follower fails with QueryRanConcurrently."""
    error: Exception
    if failure.code is not None:
        error = wrap_clickhouse_query_error(ServerException(failure.message, code=failure.code))
    else:
        cls = getattr(hogql_errors, failure.class_name or "", None)
        if not _is_shareable_hogql_error(cls):
            return None
        try:
            error = cls(failure.message, start=failure.start, end=failure.end, fix=failure.fix)
        except TypeError:
            return None
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


# The breaker context that follows the original message. It carries no failure count and no wait
# estimate: a replay that escapes to error tracking is grouped by its message, and those two values
# move on every replay, so one long-running condition would split into a new issue group each time.
BREAKER_REPLAY_SUFFIX = "This query failed in a way that will repeat, so it was not run again. Try it again later."


def build_failure_exception(record: QueryFailureRecord, *, with_scan: bool = False) -> APIException:
    """Rebuild the remembered failure with its original exception class, so status codes and
    frontend error handling stay identical to a fresh failure. The original message leads and
    the breaker context follows it. ``with_scan`` puts the first failure's query scan pointer on
    the copy, for a reader allowed to see it."""
    error = FAILURE_KIND_EXCEPTIONS[record.kind](detail=f"{record.detail} {BREAKER_REPLAY_SUFFIX}")
    error.served_from_query_failure_cache = True  # type: ignore[attr-defined]
    if with_scan and record.query_scan is not None:
        error.cache_key = record.cache_key  # type: ignore[attr-defined]
        error.query_scan = record.query_scan  # type: ignore[attr-defined]
    return error
