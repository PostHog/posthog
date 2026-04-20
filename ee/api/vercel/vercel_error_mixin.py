from typing import Any

from rest_framework.exceptions import APIException
from rest_framework.response import Response


class VercelErrorResponseMixin:
    """Mixin to format DRF exceptions into Vercel's required error schema.

    Delegates to the global exception handler (drf-exceptions-hog) for reporting
    and capture_exception, then reformats the response for Vercel's API contract.
    """

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)  # type: ignore[misc]
        response.data = self._format_vercel_error(exc)
        return response

    @staticmethod
    def _format_vercel_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, APIException):
            detail = exc.detail
            if isinstance(detail, list):
                message = " ".join(str(item) for item in detail)
            elif isinstance(detail, dict):
                message = " ".join(f"{k}: {v}" for k, v in detail.items())
            else:
                message = str(detail)
        else:
            message = "An internal error occurred. Please try again."

        return {
            "error": {
                "code": "request_failed",
                "message": message,
                "user": {"message": message, "url": None},
            }
        }
