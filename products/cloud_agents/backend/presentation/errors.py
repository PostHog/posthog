"""Turn `CloudAgentsError` into the standard PostHog error response."""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import APIException, ErrorDetail, ValidationError
from rest_framework.response import Response

from ..facade.contracts import CloudAgentsError, InvalidInput


class CloudAgentsAPIError(APIException):
    def __init__(self, error: CloudAgentsError) -> None:
        super().__init__(detail=error.message, code=error.code)
        self.status_code = error.status_code
        retry_after = getattr(error, "retry_after", None)
        if retry_after:
            # DRF's exception handler writes `wait` to the Retry-After header.
            self.wait = retry_after


def to_api_exception(error: CloudAgentsError) -> APIException:
    if isinstance(error, InvalidInput) and error.attr:
        return ValidationError({error.attr: [ErrorDetail(error.message, code=error.code)]})
    return CloudAgentsAPIError(error)


class CloudAgentsErrorHandlingMixin:
    """Views raise or let through a `CloudAgentsError`. This mixin gives it the correct status and body."""

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, CloudAgentsError):
            exc = to_api_exception(exc)
        handler: Any = super().handle_exception  # type: ignore[misc]
        return handler(exc)
