from clickhouse_driver.errors import NetworkError, SocketTimeoutError
from rest_framework.exceptions import APIException

from posthog.hogql.errors import BaseHogQLError

from posthog.dataclasses import frozen
from posthog.errors import QueryErrorCategory, classify_query_error

from products.access_control.backend.facade.user_access_control import UserAccessControlError

from ee.hogai.tool_errors import MaxToolError, MaxToolFatalError, MaxToolRetryableError, MaxToolTransientError

# Reported alongside the `QueryErrorCategory` values. A lost or timed-out connection never reaches
# ClickHouse, so the backend has no category for it, and the agent must read it as "retry", never as
# "the query is wrong".
TRANSPORT_CATEGORY = "transport"

# Cluster pressure and a dropped connection both clear on their own, so the agent waits instead of
# rewriting a query that was correct.
_RETRY_UNCHANGED_CATEGORIES = frozenset(
    {QueryErrorCategory.RATE_LIMITED, QueryErrorCategory.CANCELLED, TRANSPORT_CATEGORY}
)
_ADJUST_INPUT_CATEGORIES = frozenset({QueryErrorCategory.USER_ERROR, QueryErrorCategory.QUERY_PERFORMANCE_ERROR})

# An unknown or transport failure carries server text — a stack trace, a driver dump — so it is
# capped before it reaches agent context. A user-facing message passes through whole.
_MAX_OPAQUE_MESSAGE_CHARS = 500


def _is_about_the_query(error: Exception) -> bool:
    """Whether the error text describes the submitted query, so the agent can correct it."""
    if getattr(error, "user_safe", False):
        return True
    return isinstance(error, BaseHogQLError | APIException | UserAccessControlError)


def _category_of(error: Exception) -> str:
    if isinstance(error, NetworkError | SocketTimeoutError):
        return TRANSPORT_CATEGORY
    category = classify_query_error(error)
    if category is QueryErrorCategory.ERROR and _is_about_the_query(error):
        return QueryErrorCategory.USER_ERROR
    return category


def _message_of(error: Exception, category: str) -> str:
    if isinstance(error, APIException):
        if isinstance(error.detail, dict):
            message = ", ".join(f"{key}: {value}" for key, value in error.detail.items())
        elif isinstance(error.detail, list):
            message = ", ".join(map(str, error.detail))
        else:
            message = str(error)
    else:
        message = str(error)
    message = message.strip() or repr(error)
    if category in _ADJUST_INPUT_CATEGORIES or len(message) <= _MAX_OPAQUE_MESSAGE_CHARS:
        return message
    return message[:_MAX_OPAQUE_MESSAGE_CHARS] + "… (truncated)"


def _retry_after_seconds_of(error: Exception) -> float | None:
    # DRF throttles carry the wait in `wait`; that is the only retry-after the query stack produces.
    wait = getattr(error, "wait", None)
    return wait if isinstance(wait, int | float) else None


@frozen
class QueryFailure:
    """Why a query run for an agent failed, in the terms the agent needs to pick its next move.

    The category, the correlation id and the capacity markers lead the message, because the MCP
    transport truncates the text before the caller reads it.
    """

    category: str
    message: str
    query_id: str | None = None
    retry_after_seconds: float | None = None
    retries_exhausted: bool = False

    @classmethod
    def diagnose(cls, error: Exception, *, query_id: str | None = None) -> "QueryFailure":
        category = _category_of(error)
        return cls(
            category=category,
            message=_message_of(error, category),
            query_id=query_id,
            retry_after_seconds=_retry_after_seconds_of(error),
        )

    @property
    def markers(self) -> str:
        parts = [f"category={self.category}"]
        if self.query_id:
            parts.append(f"query_id={self.query_id}")
        if self.category == QueryErrorCategory.RATE_LIMITED:
            parts.append("overloaded=yes")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after_seconds={self.retry_after_seconds:.0f}")
        if self.retries_exhausted:
            parts.append("retries_exhausted=yes")
        return ", ".join(parts)

    def to_error(self) -> MaxToolError:
        if self.category in _RETRY_UNCHANGED_CATEGORIES:
            error_class: type[MaxToolError] = MaxToolTransientError
        elif self.category in _ADJUST_INPUT_CATEGORIES:
            error_class = MaxToolRetryableError
        else:
            error_class = MaxToolFatalError
        return error_class(f"Query failed [{self.markers}]: {self.message}")
