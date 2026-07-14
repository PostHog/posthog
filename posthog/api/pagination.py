from typing import Optional

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request

# Postgres bigint upper bound. `limit`/`offset` are spliced straight into the SQL
# LIMIT/OFFSET clauses, both of which are bigint; a larger value raises
# NumericValueOutOfRange, which surfaces as an unhandled 500 before any row is read.
MAX_PAGINATION_VALUE = 9223372036854775807


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """Repo-wide default paginator.

    DRF's LimitOffsetPagination reads `limit`/`offset` from the query string with no
    upper bound and splices them into SQL LIMIT/OFFSET. A value past the Postgres bigint
    range crashes the query with a 500 (`NumericValueOutOfRange`). Reject out-of-range
    values with a 400 instead, so unbounded input can't take an endpoint down.
    """

    def get_limit(self, request: Request) -> Optional[int]:
        self._reject_out_of_range(request, self.limit_query_param)
        return super().get_limit(request)

    def get_offset(self, request: Request) -> int:
        self._reject_out_of_range(request, self.offset_query_param)
        return super().get_offset(request)

    @staticmethod
    def _reject_out_of_range(request: Request, param: str) -> None:
        raw = request.query_params.get(param)
        if raw is None:
            return
        try:
            value = int(raw)
        except (TypeError, ValueError):
            # Non-integer input is already handled gracefully by DRF (falls back to the
            # default limit / a zero offset), so leave it to the parent implementation.
            return
        if value > MAX_PAGINATION_VALUE:
            raise ValidationError({param: f"Value may not exceed {MAX_PAGINATION_VALUE}."})
