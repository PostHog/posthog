from typing import Any, Optional

from django.db.models import QuerySet

from rest_framework.pagination import LimitOffsetPagination

# A page above this many rows is never a real product request, and a page this deep is past the
# end of every list we serve.
MAX_PAGE_LIMIT = 10_000
MAX_PAGE_OFFSET = 1_000_000_000


def stable_queryset_ordering(queryset: QuerySet) -> QuerySet:
    """Add the primary key as a final ordering term for a paginated queryset."""
    if queryset.query.is_sliced or queryset.query.group_by is not None:
        return queryset

    ordering = queryset.query.order_by or queryset.query.extra_order_by or queryset.model._meta.ordering
    if not ordering:
        return queryset.order_by("pk")

    primary_key = queryset.model._meta.pk.name
    if any(str(term).lstrip("-") in {"pk", primary_key} for term in ordering):
        return queryset

    direction = "-" if str(ordering[0]).startswith("-") else ""
    return queryset.order_by(*ordering, f"{direction}pk")


class ClampedLimitOffsetPagination(LimitOffsetPagination):
    """Bounds `limit` and `offset` before they reach the database.

    Plain `LimitOffsetPagination` passes any positive integer through as the SQL LIMIT and
    OFFSET, and Postgres rejects a value above a bigint, so an oversized request answers with a
    500 instead of a page. Clamping keeps the envelope correct: `count` and the `next` link stay
    accurate, so a client that asked for more rows than one page holds reads the rest from `next`.
    """

    max_limit = MAX_PAGE_LIMIT

    def get_offset(self, request) -> int:
        return min(super().get_offset(request), MAX_PAGE_OFFSET)


class PrecountedLimitOffsetPagination(ClampedLimitOffsetPagination):
    """Pages a queryset that the view has already bounded with LIMIT and OFFSET.

    `LimitOffsetPagination` counts with `len(queryset)` and then slices the result in Python. A
    `RawQuerySet` answers both by fetching every row, so one page costs a read of the whole result
    set. Views that page in SQL run their own count statement and hand the total over with
    `set_count`. Without a count this behaves exactly like `LimitOffsetPagination`, so a view that
    also returns unbounded querysets keeps working.
    """

    count: Optional[int] = None

    def set_count(self, count: int) -> None:
        self.count = count

    def paginate_queryset(self, queryset, request, view=None) -> Optional[list[Any]]:
        if self.count is None:
            return super().paginate_queryset(queryset, request, view)

        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)
        self.request = request
        if self.count == 0 or self.offset > self.count:
            return []

        return list(queryset)
