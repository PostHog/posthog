"""
Export Failure Classification

Classifies export failures into categories for observability and alerting.
"""

from django.db import OperationalError

from prometheus_client import Counter
from urllib3.exceptions import MaxRetryError, ProtocolError

from posthog.hogql.errors import (
    QueryError,
    SyntaxError as HogQLSyntaxError,
)

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import (
    CHQueryErrorIllegalAggregation,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorS3Error,
    CHQueryErrorTooManySimultaneousQueries,
    CHQueryErrorTypeMismatch,
    CHQueryErrorUnknownFunction,
)
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

# =============================================================================
# Export Failure Classification
# =============================================================================
#
# failure_type values stored on ExportedAsset:
#   - "timeout_generation": Export timed out during asset generation (Celery soft
#     timeout or asyncio timeout in subscriptions)
#   - "user": Errors the user can fix by modifying their query or reducing scope
#   - "system": Infrastructure/capacity errors that may resolve with retries
#   - "unknown": Errors needing investigation to properly classify
#
# To classify a new error:
#   1. If it's a timeout during generation -> add to TIMEOUT_ERROR_NAMES
#   2. If user can fix it (bad query, date range too large) -> add to USER_QUERY_ERRORS
#   3. If it's transient infrastructure (capacity, network) -> add to EXCEPTIONS_TO_RETRY
#   4. If uncertain, leave uncategorized and investigate the root cause
#
# These tuples are authoritative. Historical rows have best-effort accuracy.
# =============================================================================

FAILURE_TYPE_USER = "user"
FAILURE_TYPE_SYSTEM = "system"
FAILURE_TYPE_UNKNOWN = "unknown"
FAILURE_TYPE_TIMEOUT_GENERATION = "timeout_generation"

EXCEPTIONS_TO_RETRY = (
    CHQueryErrorS3Error,
    CHQueryErrorTooManySimultaneousQueries,
    OperationalError,
    ProtocolError,
    ConcurrencyLimitExceeded,
    MaxRetryError,
    ClickHouseAtCapacity,
)

USER_QUERY_ERRORS = (
    QueryError,
    HogQLSyntaxError,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorUnknownFunction,
    CHQueryErrorTypeMismatch,
    CHQueryErrorIllegalAggregation,
)

# Intentionally uncategorized errors (neither retryable nor user errors):
# - CHQueryErrorUnsupportedMethod: Known to be caused by missing UDFs (infrastructure issue, but not retryable)
# These should be revisited as we gather more data on their root causes.

# Exception class names for string-based classification (used in backfill)
USER_QUERY_ERROR_NAMES = frozenset(cls.__name__ for cls in USER_QUERY_ERRORS)
SYSTEM_ERROR_NAMES = frozenset(cls.__name__ for cls in EXCEPTIONS_TO_RETRY)
TIMEOUT_ERROR_NAMES = frozenset(
    [
        "SoftTimeLimitExceeded",  # Celery soft timeout
        "TimeoutError",  # asyncio.wait_for timeout
    ]
)

# Prometheus counter for export failures
EXPORT_FAILED_COUNTER = Counter(
    "exporter_task_failed",
    "An export task failed",
    labelnames=["type", "failure_type"],
)


def classify_failure_type(exception: Exception | str) -> str:
    """Classify an exception into failure_type.

    Pass an Exception or exception class name (str) for classification.
    """
    exception_type = type(exception).__name__ if isinstance(exception, Exception) else exception

    if exception_type:
        if exception_type in TIMEOUT_ERROR_NAMES:
            return FAILURE_TYPE_TIMEOUT_GENERATION
        if exception_type in USER_QUERY_ERROR_NAMES:
            return FAILURE_TYPE_USER
        if exception_type in SYSTEM_ERROR_NAMES:
            return FAILURE_TYPE_SYSTEM
    return FAILURE_TYPE_UNKNOWN


def is_user_query_error_type(exception_type: str | None) -> bool:
    """Check if an exception type is a user query error."""
    return exception_type in USER_QUERY_ERROR_NAMES
