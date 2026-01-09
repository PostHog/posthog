from django.db import OperationalError

from billiard.exceptions import SoftTimeLimitExceeded
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
#   - "user": Errors the user can fix by modifying their query or reducing scope
#   - "system": Infrastructure/capacity errors that may resolve with retries
#   - "timeout_generation": Export timed out during asset generation
#   - "unknown": Errors needing investigation to properly classify
#
# These tuples are authoritative. Historical rows have best-effort accuracy.
# =============================================================================

FAILURE_TYPE_USER = "user"
FAILURE_TYPE_SYSTEM = "system"
FAILURE_TYPE_TIMEOUT_GENERATION = "timeout_generation"
FAILURE_TYPE_UNKNOWN = "unknown"

EXCEPTIONS_TO_RETRY = (
    CHQueryErrorS3Error,
    CHQueryErrorTooManySimultaneousQueries,
    OperationalError,
    ProtocolError,
    ConcurrencyLimitExceeded,
    MaxRetryError,  # This is from urllib, e.g. HTTP retries instead of "job retries"
    ClickHouseAtCapacity,
)

USER_QUERY_ERRORS = (
    QueryError,
    HogQLSyntaxError,
    ClickHouseQueryMemoryLimitExceeded,  # Users should reduce the date range on their query (or materialise)
    ClickHouseQueryTimeOut,  # Users should switch to materialised queries if they run into this
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorUnknownFunction,
    CHQueryErrorTypeMismatch,
    CHQueryErrorIllegalAggregation,
)

TIMEOUT_ERRORS = (
    SoftTimeLimitExceeded,
    TimeoutError,
)

# Intentionally uncategorized errors (neither retryable nor user errors):
# - CHQueryErrorUnsupportedMethod: Known to be caused by missing UDFs (infrastructure issue, but not retryable)
# These should be revisited as we gather more data on their root causes.

# Exception class names for string-based classification (used in backfill)
USER_QUERY_ERROR_NAMES = frozenset(cls.__name__ for cls in USER_QUERY_ERRORS)
SYSTEM_ERROR_NAMES = frozenset(cls.__name__ for cls in EXCEPTIONS_TO_RETRY)
TIMEOUT_ERROR_NAMES = frozenset(cls.__name__ for cls in TIMEOUT_ERRORS)


def classify_failure_type(exception: Exception | str) -> str:
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
    return classify_failure_type(exception_type) is FAILURE_TYPE_USER
