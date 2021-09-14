from typing import Dict, Literal, Optional, TypedDict

from django.core.signals import got_request_exception
from django.http.request import HttpRequest
from django.http.response import JsonResponse
from rest_framework import status
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception


class RequestParsingError(Exception):
    pass


class EnterpriseFeatureException(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_detail = "This is an Enterprise feature."


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
    if not isinstance(exception, APIException):
        capture_exception(exception)

        # NOTE: to make sure we get exception tracebacks in test responses, we need
        # to make sure this signal is called. The django test client uses this to
        # pull out the exception traceback.
        #
        # See https://github.com/django/django/blob/ecf87ad513fd8af6e4a6093ed918723a7d88d5ca/django/test/client.py#L714
        got_request_exception.send(sender=None, request=context["request"])


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
