from typing import Any, Optional, TypedDict

from django.http.request import HttpRequest
from django.http.response import JsonResponse

import structlog
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class RequestParsingError(Exception):
    pass


class UnspecifiedCompressionFallbackParsingError(Exception):
    pass


class QuotaLimitExceeded(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "quota_limit_exceeded"
    default_detail = "Your organization reached its billing limit for this resource. Increase the limits in Billing settings, or ask an org admin to do so."


class EnterpriseFeatureException(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "payment_required"

    def __init__(self, feature: Optional[str] = None) -> None:
        super().__init__(
            detail=(
                f"{feature.capitalize().replace('_', ' ') if feature else 'This feature'} is part of the premium PostHog offering. "
                + (
                    "To use it, subscribe to PostHog Cloud with a generous free tier."
                    if is_cloud()
                    else "Self-hosted licenses are no longer available for purchase. Please contact sales@posthog.com to discuss options."
                )
            )
        )


class PaidFeatureException(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "payment_required"

    def __init__(self, feature: Optional[str] = None) -> None:
        feature_name = feature.capitalize().replace("_", " ") if feature else "This feature"
        super().__init__(detail=f"{feature_name} requires a paid PostHog plan. Please upgrade to access this feature.")


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class ClickHouseAtCapacity(APIException):
    status_code = 503
    default_detail = (
        "Queries are a little too busy right now. We're working to free up resources. Please try again later."
    )


class ClickHouseEstimatedQueryExecutionTimeTooLong(APIException):
    status_code = 512  # Custom error code
    default_detail = "Estimated query execution time is too long. Try reducing its scope by changing the time range."


class ClickHouseQuerySizeExceeded(APIException):
    default_detail = "Query size exceeded."


class ClickHouseQueryTimeOut(APIException):
    status_code = 504
    default_detail = "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize."


class ClickHouseQueryMemoryLimitExceeded(APIException):
    # 512 (like ClickHouseEstimatedQueryExecutionTimeTooLong) so the frontend surfaces the detail
    # in the actionable "problem with this query" panel rather than the generic error state.
    status_code = 512  # Custom error code
    # Stable machine-readable code so the frontend can recognise out-of-memory failures without
    # matching on the (translatable, changeable) detail copy. Keep in sync with the frontend
    # CLICKHOUSE_MEMORY_LIMIT_ERROR_CODE constant.
    default_code = "clickhouse_memory_limit_exceeded"
    default_detail = "This query ran out of memory before it could finish, usually because it's scanning too much data. Try a shorter date range or narrower filters, or see our docs for more ways to speed it up: https://posthog.com/docs/product-analytics/troubleshooting#how-do-i-speed-up-my-insights-and-queries"


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


def exception_handler(exc: Exception, context: ExceptionContext) -> Optional[Response]:
    """
    Wraps drf-exceptions-hog and, on 401, advertises the OAuth protected resource
    metadata document via WWW-Authenticate per RFC 9728, so that MCP-style agents
    can bootstrap from a stock 401.
    """
    # Imported lazily: exceptions_hog calls a non-lazy gettext at module import time,
    # which raises AppRegistryNotReady when posthog.exceptions is imported during
    # manage.py bootstrap (before Django apps are loaded).
    from exceptions_hog import exception_handler as _exceptions_hog_handler

    # Imported lazily to avoid pulling settings into module import.
    from posthog.utils import absolute_uri

    response = _exceptions_hog_handler(exc, context)
    if response is not None and response.status_code == status.HTTP_401_UNAUTHORIZED:
        # A view may pin its own challenge (e.g. the skills marketplace git endpoints, which
        # git clients can only satisfy with Basic — they cannot complete a Bearer/OAuth flow).
        view_challenge = getattr(context.get("view"), "www_authenticate_challenge", None)
        if view_challenge:
            # Strip CR/LF defensively — this is a view-supplied value, so never let it inject
            # additional response headers even if a future view derives it from request data.
            response["WWW-Authenticate"] = view_challenge.replace("\r", "").replace("\n", "")
        else:
            # Pin to SITE_URL rather than request.build_absolute_uri(): with permissive
            # ALLOWED_HOSTS, the Host header can otherwise steer the discovery hint to an
            # attacker-controlled origin.
            metadata_url = absolute_uri("/.well-known/oauth-protected-resource")
            response["WWW-Authenticate"] = f'Bearer resource_metadata="{metadata_url}"'
    return response
