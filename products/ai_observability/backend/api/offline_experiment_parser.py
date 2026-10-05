import json
import math
from collections.abc import Mapping
from decimal import Decimal, DecimalException
from typing import IO, cast

from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser

MAX_UPLOAD_BODY_BYTES = 5 * 1024 * 1024


class OfflineEvaluationRequestTooLarge(APIException):
    status_code = 413
    default_detail = "Request bodies must be 5 MiB or smaller. Split results into smaller batches."
    default_code = "request_too_large"


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number == 0 and Decimal(value) != 0:
        raise ValueError("Number is outside the supported binary64 range.")
    return number


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON numbers are not supported.")


class OfflineEvaluationJSONParser(JSONParser):
    def parse(
        self, stream: IO[bytes], media_type: str | None = None, parser_context: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        # Bound the stream itself; Content-Length can be absent or inaccurate.
        body = stream.read(MAX_UPLOAD_BODY_BYTES + 1)
        if len(body) > MAX_UPLOAD_BODY_BYTES:
            raise OfflineEvaluationRequestTooLarge
        try:
            value = json.loads(body, parse_float=_finite_float, parse_constant=_invalid_constant)
            if not isinstance(value, dict):
                raise ValueError("Request bodies must be JSON objects.")
            return cast(dict[str, object], value)
        except (ValueError, UnicodeError, RecursionError, DecimalException) as error:
            raise ParseError("Provide valid JSON with finite, representable numbers.") from error
