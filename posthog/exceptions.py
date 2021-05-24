from typing import Optional

from django.http.response import JsonResponse
from rest_framework import status
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception


class RequestParsingError(Exception):
    pass


def exception_reporting(exception: Exception, *args, **kwargs) -> None:
    """
    Determines which exceptions to report and sends them to Sentry.
    Used through drf-exceptions-hog
    """
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
