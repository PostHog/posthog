from typing import Any, Optional

from django.db.models import QuerySet

from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


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


class PrecountedLimitOffsetPagination(LimitOffsetPagination):
    """Pages a queryset that the view has already bounded with LIMIT and OFFSET.

    `LimitOffsetPagination` counts with `len(queryset)` and then slices the result in Python. A
    `RawQuerySet` answers both by fetching every row, so one page costs a read of the whole result
    set. Views that page in SQL run their own count statement and hand the total over with
    `set_count`. Without a count this behaves exactly like `LimitOffsetPagination`, so a view that
    also returns unbounded querysets keeps working.
    """

    count: Optional[int] = None
    page_size_returned: int = 0

    def set_count(self, count: int) -> None:
        self.count = count

    def _offset_is_past_the_end(self) -> bool:
        return (self.offset or 0) > (self.count or 0)

    def paginate_queryset(self, queryset, request, view=None) -> Optional[list[Any]]:
        if self.count is None:
            return super().paginate_queryset(queryset, request, view)

        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)
        self.request = request
        if self.count == 0 or self._offset_is_past_the_end():
            self.page_size_returned = 0
            return []

        page = list(queryset)
        self.page_size_returned = len(page)
        return page


class CappedCountLimitOffsetPagination(PrecountedLimitOffsetPagination):
    """Pages a view whose count stops at a cap, so `count` is a lower bound rather than a total.

    Kept separate from `PrecountedLimitOffsetPagination` so only the views that cap carry
    `count_is_capped` in their response schema.
    """

    count_is_capped: bool = False

    def set_count(self, count: int, is_capped: bool = False) -> None:
        super().set_count(count)
        self.count_is_capped = is_capped

    def _offset_is_past_the_end(self) -> bool:
        # The count is a lower bound, so it says nothing about where the rows end. Only an empty page does.
        return False if self.count_is_capped else super()._offset_is_past_the_end()

    def get_next_link(self) -> Optional[str]:
        # The base class drops `next` once `offset + limit >= count`, which a capped count reaches early.
        if self.count_is_capped and self.limit and self.request and self.page_size_returned >= self.limit:
            url = self.request.build_absolute_uri()
            url = replace_query_param(url, self.limit_query_param, self.limit)
            return replace_query_param(url, self.offset_query_param, (self.offset or 0) + self.limit)
        return super().get_next_link()

    def get_paginated_response(self, data: Any) -> Response:
        response = super().get_paginated_response(data)
        response.data["count_is_capped"] = self.count_is_capped
        return response

    def get_paginated_response_schema(self, schema: dict) -> dict:
        paginated = super().get_paginated_response_schema(schema)
        paginated["properties"]["count_is_capped"] = {
            "type": "boolean",
            "description": "True when `count` stopped at a cap, so it is a lower bound and `next` keeps paging past it.",
        }
        return paginated
