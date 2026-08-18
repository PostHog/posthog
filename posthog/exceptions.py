from typing import Any, Optional, TypedDict

from django.http.request import HttpRequest
from django.http.response import JsonResponse

import structlog
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
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


class APIQueriesQuotaExceeded(QuotaLimitExceeded):
    default_code = "api_queries_quota_exceeded"
    default_detail = (
        "Your organization has read more query data over the API than its free allowance for this month. "
        "API queries will be available again when the allowance resets. "
        "Upgrade your plan in Billing settings to restore access sooner, or ask an org admin to do so."
    )


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


class DatabaseSchemaUnavailable(APIException):
    # The schema request backs the SQL editor's table list, so a bare 500 leaves the sidebar looking
    # like an empty project. A stable code lets the client tell "we couldn't read your schema" apart
    # from any other server error.
    status_code = 503
    default_detail = "Couldn't load your project's schema. Try again, and if it keeps happening contact support."
    default_code = "database_schema_unavailable"


class DatabaseUnavailable(APIException):
    # A transient Postgres failure (connection-pool saturation, failover, restart) that reached a
    # request handler. 503 + Retry-After tells clients to back off and retry instead of treating it
    # as a permanent failure, and keeps the driver's raw error text out of the response.
    status_code = 503
    default_code = "database_unavailable"
    default_detail = "We couldn't reach the database just now. Please try again in a moment."
    # Seconds a well-behaved client should wait before retrying, copied onto Retry-After by
    # exception_handler below.
    retry_after = 1


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


class ClickHouseBytesLimitExceeded(ValidationError):
    # A fresh TOO_MANY_BYTES surfaces as ValidationError(str(error), "too_many_bytes") in the
    # query API, so the breaker's replay must produce the same status and machine code.
    default_code = "too_many_bytes"


class ClickHouseQueryTimeOut(APIException):
    status_code = 504
    default_detail = "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize."


class ClickHouseQueryMemoryLimitExceeded(APIException):
    # Custom code in the actionable-validation family (400/512/513) the frontend routes to the
    # "problem with this query" panel. Distinct from 512 (query-too-slow) so an out-of-memory
    # failure is never mistaken for a timeout on either the client or in status-based alerting.
    status_code = 513
    # Stable machine-readable code so the frontend can recognise out-of-memory failures without
    # matching on the (translatable, changeable) detail copy. Keep in sync with the frontend
    # CLICKHOUSE_MEMORY_LIMIT_ERROR_CODE constant.
    default_code = "clickhouse_memory_limit_exceeded"
    default_detail = "This query ran out of memory before it could finish, usually because it's scanning too much data. Try a shorter date range or narrower filters, or see our docs for more ways to speed it up: https://posthog.com/docs/product-analytics/troubleshooting#how-do-i-speed-up-my-insights-and-queries"
    is_per_query_limit = False


class ClickHouseClusterMemoryLimitExceeded(ClickHouseQueryMemoryLimitExceeded):
    """ClickHouse refused the query because the server-wide or per-user memory ceiling was full.

    The query itself can be sized fine, so this belongs to `CH_TRANSIENT_ERRORS` and every retry
    mechanism that references that tuple can get past it. Subclassing keeps the 513 status and the
    machine-readable code, but the detail tells the user to wait rather than shrink a fine query.
    """

    default_detail = (
        "We're under heavy load right now and couldn't finish this query. Please try again in a few minutes."
    )


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

    # Imported lazily to keep django.db off this module's import path — it loads during manage.py
    # bootstrap, before Django apps are ready.
    from posthog.db_errors import is_transient_db_error

    # Imported lazily to avoid pulling settings into module import.
    from posthog.utils import absolute_uri

    # A transient Postgres failure (pgbouncer pool-wait `query_wait_timeout`, failover, restart)
    # reaching a request handler otherwise escapes as an unhandled 500 with the generic "A server
    # error occurred." detail, and gets captured under whichever Django-internal error sits in its
    # __context__ chain (an FK cache-miss KeyError on `current_organization` masks it in error
    # tracking). Map it to a retryable 503 before drf-exceptions-hog reports it, so clients back
    # off and the real cause is never reported as a KeyError.
    if is_transient_db_error(exc):
        logger.warning("db_transient_error", path=context["request"].path, error=str(exc))
        exc = DatabaseUnavailable()

    response = _exceptions_hog_handler(exc, context)
    if response is not None and isinstance(exc, DatabaseUnavailable):
        response["Retry-After"] = str(exc.retry_after)
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
