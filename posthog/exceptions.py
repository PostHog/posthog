import random
from collections.abc import Sequence
from typing import Any, Optional, Protocol, TypedDict

from django.http.request import HttpRequest
from django.http.response import JsonResponse

import structlog
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.cloud_utils import is_cloud
from posthog.exceptions_capture import capture_exception
from posthog.scopes import (
    INTERNAL_API_SCOPE_OBJECTS,
    scopes_covered_by_legacy_fallback,
    scopes_not_covered,
    scopes_within_ceiling,
)

logger = structlog.get_logger(__name__)


class RequestParsingError(Exception):
    pass


class UnspecifiedCompressionFallbackParsingError(Exception):
    pass


class QuotaLimitExceeded(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "quota_limit_exceeded"
    default_detail = "Your organization reached its billing limit for this resource. Increase the limits in Billing settings, or ask an org admin to do so."


class APIQueriesBudgetExceeded(Throttled):
    # DRF sets this in Throttled.__init__ and its handler turns it into Retry-After; the stubs omit it.
    wait: Optional[float]

    default_code = "api_queries_budget_exceeded"
    # DRF appends "Expected available in N seconds." to this, so the wait is not repeated here.
    default_detail = (
        "This project used its hourly budget of data read by API queries. "
        "To stay under it, read less data per query or run queries less often. "
        "See https://posthog.com/docs/sql/optimizing-queries for ways to read less."
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


class InsufficientScope(PermissionDenied):
    """A 403 for a token that lacks a scope the request needs.

    Raise it wherever code finds a missing scope. The exception handler decides if the response
    carries an RFC 6750 section 3.1 `insufficient_scope` challenge, so callers never check the token type.
    `required_scopes` are the scopes the request requires. The MCP step-up flow has the client union
    them with the scopes it holds, so a check that guards one extra scope can name only that scope.
    """

    def __init__(self, required_scopes: Sequence[str], detail: str | None = None) -> None:
        super().__init__(detail=detail or f"API key missing required scope '{required_scopes[0]}'")
        self.required_scopes = list(required_scopes)


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


class ClickHouseAtCapacity(APIException):
    wait: int
    status_code = 503
    default_code = "clickhouse_at_capacity"
    default_detail = (
        "Queries are a little too busy right now. We're working to free up resources. Please try again later."
    )

    def __init__(self, detail: Optional[str] = None, code: Optional[str] = None) -> None:
        super().__init__(detail=detail, code=code)
        # Spread retries across requests while keeping a minimum recovery window.
        self.wait = random.randint(5, 20)


class QueryRanConcurrently(APIException):
    """Raised by a query single flight follower whose leader left nothing to serve or rebuild: the
    leader failed in a way that cannot be shared, died, or held its lock past the limit."""

    status_code = 503
    default_code = "query_ran_concurrently"
    default_detail = "This query was already running and its result couldn't be reused. Try again in a moment."


# Failures that clear on their own. A caller that reads one of these codes should wait and run the same query again.
TRANSIENT_QUERY_ERROR_CODES = frozenset({ClickHouseAtCapacity.default_code, QueryRanConcurrently.default_code})


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
    user_safe = True
    status_code = 504
    default_detail = "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize."


class ClickHouseQueryMemoryLimitExceeded(APIException):
    user_safe = True
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


class FieldedValidationError(Protocol):
    """A framework-free validation error, as a product's internals raise it."""

    message: str
    field: str | None


def as_drf_validation_error(error: FieldedValidationError) -> ValidationError:
    """The DRF equivalent of a framework-free validation error, keyed by field when it names one."""
    if error.field:
        return ValidationError({error.field: [error.message]})
    return ValidationError(error.message)


def first_error_message(detail: Any) -> str:
    """The first message in a DRF error detail, which nests messages in dicts and lists."""
    while isinstance(detail, (dict, list)) and detail:
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return str(detail)


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
    elif response is not None and isinstance(exc, InsufficientScope):
        if challenge := _insufficient_scope_challenge(context.get("request"), exc.required_scopes):
            response["WWW-Authenticate"] = challenge
    return response


def _insufficient_scope_challenge(request: object, required_scopes: Sequence[str]) -> str | None:
    """Only tokens from step-up apps get the challenge. Every other caller gets the same 403 without it."""
    from posthog.auth import OAuthAccessTokenAuthentication  # noqa: PLC0415 - posthog.auth needs the app registry

    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication) or not authenticator.access_token.supports_step_up:
        return None
    # Internal scopes cannot be granted at consent, so a challenge naming one could never succeed.
    if any(scope.split(":", 1)[0] in INTERNAL_API_SCOPE_OBJECTS for scope in required_scopes):
        return None
    # Consent drops a scope outside the app's ceiling, so the client would re-consent and still lack it.
    # Only the scopes the token lacks matter: a held or legacy-covered scope needs no new grant.
    held = str(authenticator.access_token.scope or "").split()
    lacking = scopes_not_covered(held, required_scopes)
    lacking = [scope for scope in lacking if scope not in scopes_covered_by_legacy_fallback(held, lacking)]
    application = authenticator.access_token.application
    if application is None or not scopes_within_ceiling(
        lacking, application.ceiling_scopes, allow_wildcard_under_empty_ceiling=True
    ):
        return None
    return f'Bearer error="insufficient_scope", scope="{" ".join(required_scopes)}"'
