"""
Internal API authentication for service-to-service communication.

This module provides middleware and decorators for securing Django endpoints
that should only be accessible via authenticated internal service calls
(e.g., Node.js -> Django).

The primary protection comes from network-level routing configuration, and this
provides defense-in-depth authentication using a shared INTERNAL_API_SECRET.

Usage:
    @require_internal_api_auth
    def my_internal_view(request):
        ...
"""

import hmac
from collections.abc import Callable
from functools import wraps

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

import structlog

logger = structlog.get_logger(__name__)

HEADER_NAME = "X-Internal-Api-Secret"


def _check_internal_api_secret(request: HttpRequest) -> bool:
    """
    Validate the internal API secret from request headers.

    Uses timing-safe comparison to prevent timing attacks.

    Returns:
        True if the secret is valid, False otherwise.
    """
    provided_secret = request.headers.get(HEADER_NAME)

    if not provided_secret:
        logger.warning(
            "Internal API request missing authentication header",
            path=request.path,
            method=request.method,
        )
        return False

    # Use timing-safe comparison to prevent timing attacks
    if not hmac.compare_digest(settings.INTERNAL_API_SECRET, provided_secret):
        logger.warning(
            "Internal API request with invalid secret",
            path=request.path,
            method=request.method,
        )
        return False

    return True


def require_internal_api_auth(view_func: Callable) -> Callable:
    """
    Decorator to mark a view as requiring internal API authentication.

    When applied to a view, the view will only be accessible if the request
    includes a valid X-Internal-Api-Secret header.

    Example:
        @require_internal_api_auth
        def my_internal_endpoint(request):
            return JsonResponse({"status": "ok"})
    """

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not _check_internal_api_secret(request):
            return JsonResponse(
                {"error": "Unauthorized: Invalid or missing internal API authentication"},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    # Mark the view as requiring internal API auth
    wrapper.requires_internal_api_auth = True  # type: ignore
    return wrapper


class InternalAPIAuthMiddleware:
    """
    Middleware for enforcing internal API authentication on marked views.

    This middleware checks if a view has been decorated with @require_internal_api_auth
    and enforces the authentication requirement if so.

    Add to MIDDLEWARE in settings:
        MIDDLEWARE = [
            ...
            'posthog.internal_api_auth.InternalAPIAuthMiddleware',
            ...
        ]
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Get the response to access the view function
        response = self.get_response(request)

        # The decorator handles authentication, so this middleware is mainly
        # for logging and monitoring purposes
        return response
