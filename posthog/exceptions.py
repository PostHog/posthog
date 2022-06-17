from typing import Optional, TypedDict

import structlog
from django.conf import settings
from django.http.request import HttpRequest
from django.http.response import JsonResponse
from rest_framework import status
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)


class RequestParsingError(Exception):
    pass


class EnterpriseFeatureException(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "payment_required"

    def __init__(self, feature: Optional[str] = None) -> None:
        super().__init__(
            detail=(
                f"{feature.capitalize() if feature else 'This feature'} is part of the premium PostHog offering. "
                + (
                    "To use it, subscribe to PostHog Cloud with a generous free tier: https://app.posthog.com/organization/billing"
                    if settings.MULTI_TENANCY
                    else "To use it, get a self-hosted license: https://license.posthog.com"
                )
            )
        )


class EstimatedQueryExecutionTimeTooLong(APIException):
    status_code = 512  # Custom error code
    default_detail = "Estimated query execution time is too long"


class ExceptionContext(TypedDict):
    request: HttpRequest


def exception_reporting(exception: Exception, context: ExceptionContext) -> None:
    """
    Determines which exceptions to report and sends them to Sentry.
    Used through drf-exceptions-hog
    """
    from posthog.api.instance_settings import get_instance_setting
    from posthog.settings.base_variables import DEBUG

    if DEBUG or get_instance_setting("CAPTURE_BACKEND_EXCEPTIONS"):
        logger.exception(exception)

    if not isinstance(exception, APIException):
        capture_exception(exception)


def generate_exception_response(
    endpoint: str,
    detail: str,
    code: str = "invalid",
    type: str = "validation_error",
    attr: Optional[str] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JsonResponse:
    """
    Generates a friendly JSON error response in line with drf-exceptions-hog for endpoints not under DRF.
    """

    from posthog.internal_metrics import incr

    incr(f"posthog_cloud_raw_endpoint_exception", tags={"endpoint": endpoint, "code": code, "type": type, "attr": attr})
    return JsonResponse({"type": type, "code": code, "detail": detail, "attr": attr}, status=status_code,)
