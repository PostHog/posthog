from typing import Any, Optional, TypedDict

from django.http.request import HttpRequest
from django.http.response import JsonResponse

import structlog
from rest_framework import status
from rest_framework.exceptions import APIException

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class RequestParsingError(Exception):
    pass


class UnspecifiedCompressionFallbackParsingError(Exception):
    pass


class EnterpriseFeatureException(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "payment_required"

    def __init__(self, feature: Optional[str] = None) -> None:
        super().__init__(
            detail=(
                f"{feature.capitalize() if feature else 'This feature'} is part of the premium PostHog offering. "
                + (
                    "To use it, subscribe to PostHog Cloud with a generous free tier."
                    if is_cloud()
                    else "Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options."
                )
            )
        )


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class ClickHouseAtCapacity(APIException):
    status_code = 503
    default_detail = (
        "Queries are a little too busy right now. We're working to free up resources. Please try again later."
    )


class EstimatedQueryExecutionTimeTooLong(APIException):
    status_code = 512  # Custom error code
    default_detail = "Estimated query execution time is too long. Try reducing its scope by changing the time range."


class QuerySizeExceeded(APIException):
    default_detail = "Query size exceeded."


class ClickHouseQueryTimeOut(APIException):
    status_code = 504
    default_detail = "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize."


class ClickHouseQueryMemoryLimitExceeded(APIException):
    status_code = 504
    default_detail = "Query has reached the max memory limit before completing. See our docs for how to improve your query memory footprint. You may need to narrow date range or materialize."


class ExceptionContext(TypedDict):
    request: HttpRequest


def exception_reporting(exception: Exception, context: ExceptionContext) -> Optional[str]:
    """
    Determines which exceptions to report and sends them to error tracking.
    Used through drf-exceptions-hog
    """
    if not isinstance(exception, APIException):
        tags = get_query_tags().model_dump(exclude_none=True)
        logger.exception(exception, path=context["request"].path, **tags)
        return capture_exception(exception)
    return None


def generate_exception_response(
    endpoint: str,
    detail: Any,
    code: str = "invalid",
    type: str = "validation_error",
    attr: Optional[str] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JsonResponse:
    """
    Generates a friendly JSON error response in line with drf-exceptions-hog for endpoints not under DRF.
    """

    # Importing here because this module is loaded before Django settings are configured,
    # and statshog relies on those being ready
    from statshog.defaults.django import statsd

    statsd.incr(
        f"posthog_cloud_raw_endpoint_exception",
        tags={"endpoint": endpoint, "code": code, "type": type, "attr": attr},
    )
    return JsonResponse({"type": type, "code": code, "detail": detail, "attr": attr}, status=status_code)
