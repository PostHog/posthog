from typing import Any

from rest_framework.exceptions import APIException
from rest_framework.status import HTTP_402_PAYMENT_REQUIRED


class LimitExceeded(APIException):
    """Raised when a team has hit a resource limit.

    Rendered as HTTP 402 Payment Required by ``exceptions_hog``. Structured
    metadata is exposed via the ``extra`` attribute, which the handler copies
    onto the JSON response body alongside ``type``/``code``/``detail``.
    """

    status_code = HTTP_402_PAYMENT_REQUIRED
    default_code = "limit_exceeded"
    default_type = "limit_exceeded"
    default_detail = "Resource limit exceeded."

    def __init__(
        self,
        *,
        limit_key: str,
        limit: int,
        current: int,
        request_id: str | None = None,
    ) -> None:
        super().__init__(detail=self.default_detail, code=self.default_code)
        self.limit_key = limit_key
        self.limit = limit
        self.current = current
        self.request_id = request_id
        self.extra: dict[str, Any] = {
            "limit_key": limit_key,
            "limit": limit,
            "current": current,
            "request": {"id": request_id} if request_id else None,
        }
