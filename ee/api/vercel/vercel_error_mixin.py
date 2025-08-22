from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework.exceptions import APIException
from typing import Any


class VercelErrorResponseMixin:
    """Mixin to format DRF exceptions into Vercel's error schema"""

    def handle_exception(self, exc):
        context: dict[str, Any] = getattr(self, "get_exception_handler_context", lambda: {})()
        response = exception_handler(exc, context)

        if response is not None:
            response.data = self._format_vercel_error(exc, response)

        return response

    def _format_vercel_error(self, exc: Exception, response: Response) -> dict[str, Any]:
        if isinstance(exc, APIException):
            detail = exc.detail
        else:
            detail = str(exc)

        if isinstance(detail, list | dict):
            message = str(detail)
        else:
            message = str(detail)

        return {
            "error": {
                "code": "request_failed",
                "message": message,
                "user": {"message": message, "url": None},
            }
        }
