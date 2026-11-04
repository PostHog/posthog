from rest_framework.exceptions import ValidationError

from posthog.hogql import errors as hogql_errors
from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import (
    CHQueryErrorCannotParseUuid,
    CHQueryErrorIllegalAggregation,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorInvalidJoinOnExpression,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorNumberOfArgumentsDoesntMatch,
    CHQueryErrorTooManyBytes,
    CHQueryErrorTypeMismatch,
    CHQueryErrorUnknownFunction,
    CHQueryErrorUnknownIdentifier,
    CHQueryErrorUnknownTable,
    CHQueryErrorUnsupportedMethod,
    ExposedCHQueryError,
)
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQuerySizeExceeded, ClickHouseQueryTimeOut

USER_QUERY_ERRORS: tuple[type[Exception], ...] = (
    ExposedHogQLError,
    hogql_errors.QueryError,
    hogql_errors.SyntaxError,
    ValidationError,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
    ExposedCHQueryError,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorUnknownFunction,
    CHQueryErrorTypeMismatch,
    CHQueryErrorIllegalAggregation,
    CHQueryErrorNumberOfArgumentsDoesntMatch,
    CHQueryErrorUnknownIdentifier,
    CHQueryErrorTooManyBytes,
    CHQueryErrorCannotParseUuid,
    ClickHouseQuerySizeExceeded,
    CHQueryErrorUnsupportedMethod,
    hogql_errors.ResolutionError,
    CHQueryErrorInvalidJoinOnExpression,
    CHQueryErrorUnknownTable,
)
