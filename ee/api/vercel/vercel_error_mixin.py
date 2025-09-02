from typing import Any

from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


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
            message = str(exc.detail)
        else:
            message = str(exc)

        return {
            "error": {
                "code": "request_failed",
                "message": message,
                "user": {"message": message, "url": None},
            }
        }
