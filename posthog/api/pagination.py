from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any, Optional, cast

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet

from rest_framework.pagination import CursorPagination, LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.utils.urls import replace_query_param

from posthog.paging import CursorBound, CursorPageRequest, Page, PageRequest

if TYPE_CHECKING:
    # DRF's generics module reads DEFAULT_PAGINATION_CLASS while it loads, which can point at this module.
    from rest_framework.generics import GenericAPIView


def stable_queryset_ordering(queryset: QuerySet) -> QuerySet:
    """Add the primary key as a final ordering term for a paginated queryset."""
    if queryset.query.is_sliced:
        return queryset
    # `group_by is True` means Django groups by every selected column of the model, primary key
    # included, so a primary key term cannot change the groups. A tuple comes from
    # `values(...).annotate(...)`, where a primary key term would split the groups.
    if queryset.query.group_by is not None and queryset.query.group_by is not True:
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


def select_page[M: Model](queryset: QuerySet[M], page: PageRequest) -> Page[M]:
    """Return one page of `queryset` and the number of rows in all of it.

    The rows are also sorted by primary key, so a page boundary between rows that share a sort value
    cannot skip or repeat a row.
    """
    count = queryset.count()
    rows = stable_queryset_ordering(queryset)[page.offset : page.offset + page.limit]
    return Page(results=list(rows), count=count)


def select_cursor_page[M: Model](
    queryset: QuerySet[M], page: CursorPageRequest, *, ordering_fields: Collection[str]
) -> Page[M]:
    """Return the rows of one cursor page of `queryset` and the number of rows in all of it.

    `ordering_fields` names the fields a client may sort by. The primary key is always allowed,
    because `StableCursorPagination` adds it as the last ordering term.
    """
    for term in page.ordering:
        if term.lstrip("-") not in ordering_fields and term.lstrip("-") != "pk":
            raise ValueError(f"Cannot order by {term!r}")

    count = queryset.count()
    first = page.ordering[0]
    queryset = stable_queryset_ordering(queryset.order_by(*page.ordering))
    if page.bound is not None:
        comparison = "lt" if page.bound.before else "gt"
        queryset = queryset.filter(**{f"{first.lstrip('-')}__{comparison}": page.bound.value})

    return Page(results=list(queryset[page.offset : page.offset + page.limit]), count=count)


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """Limit/offset pages of at most `max_limit` rows.

    DRF has no upper bound by default, so `?limit=` could ask one request to read a whole table.
    A larger limit is cut to `max_limit`, and the schema states the maximum.
    """

    max_limit = 1000

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        parameters = super().get_schema_operation_parameters(view)
        for parameter in parameters:
            if parameter["name"] == self.limit_query_param:
                parameter["schema"]["maximum"] = self.max_limit
        return parameters


class FacadeLimitOffsetPagination(BoundedLimitOffsetPagination):
    """Builds the standard limit/offset response from a page that a facade read in SQL.

    A facade returns contracts, not a queryset, so it cannot hand its rows to `paginate_queryset`
    without loading the whole list. The view passes a `fetch` function instead. This paginator reads
    the limit and offset from the request, asks `fetch` for that page, and keeps the response shape
    and links of `LimitOffsetPagination`.
    """

    def get_paginated_facade_response[T](
        self,
        request: Request,
        view: "GenericAPIView",
        fetch: Callable[[PageRequest], Page[T]],
        serializer_class: type[BaseSerializer] | None = None,
    ) -> Response:
        limit = self.get_limit(request)
        if limit is None:
            raise ImproperlyConfigured(f"{type(self).__name__} needs a default_limit to page a facade list.")
        self.request = request
        self.limit = limit
        self.offset = self.get_offset(request)
        page = fetch(PageRequest(limit=limit, offset=self.offset))
        self.count = page.count

        serializer_class = serializer_class or view.get_serializer_class()
        serializer = serializer_class(page.results, many=True, context=view.get_serializer_context())
        return self.get_paginated_response(serializer.data)


class StableCursorPagination(CursorPagination):
    """Cursor pages with a stable row order, and a `count` like the limit/offset response.

    A cursor stores the value of the first ordering field. When rows share that value, their order
    must be the same in every query, so the primary key is added as the last ordering term, in the
    direction of the first term. Paging forward then never skips or repeats a row. A `previous` link
    can still land on the wrong rows when more rows share one value than fit on a page, because the
    cursor does not store the primary key.
    """

    def get_ordering(self, request: Request, queryset: Any, view: Any) -> tuple[str, ...]:
        ordering = super().get_ordering(request, queryset, view)
        model = getattr(queryset, "model", None)
        primary_key = model._meta.pk.name if model is not None else "pk"
        if any(term.lstrip("-") in {"pk", primary_key} for term in ordering):
            return ordering
        direction = "-" if ordering[0].startswith("-") else ""
        return (*ordering, f"{direction}pk")

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> Optional[list[Any]]:
        self.counted_rows = queryset
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data: Any) -> Response:
        return Response(
            {
                "count": self.counted_rows.count(),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema: dict) -> dict:
        paginated = super().get_paginated_response_schema(schema)
        paginated["required"] = ["count", "results"]
        paginated["properties"] = {
            "count": {"type": "integer", "example": 123},
            **paginated["properties"],
        }
        return paginated


class _FacadePageSource[T]:
    """Stands in for the queryset that `CursorPagination.paginate_queryset` pages through.

    The paginator only orders the queryset, filters it on the cursor position and slices it. This
    records the ordering and the position, and the slice reads that page through the facade. So DRF
    still decodes and encodes every cursor.
    """

    def __init__(
        self,
        fetch: Callable[[CursorPageRequest], Page[T]],
        ordering: tuple[str, ...] = (),
        bound: CursorBound | None = None,
        fetched: list[Page[T]] | None = None,
    ) -> None:
        self._fetch = fetch
        self._ordering = ordering
        self._bound = bound
        # Every copy shares one list, so the source the paginator received can report the count of
        # the page that a later copy fetched.
        self._fetched: list[Page[T]] = fetched if fetched is not None else []

    def order_by(self, *ordering: str) -> "_FacadePageSource[T]":
        return _FacadePageSource(self._fetch, ordering, self._bound, self._fetched)

    def filter(self, **lookup: str) -> "_FacadePageSource[T]":
        # The only filter is the position, as `<first ordering field>__lt` or `__gt`.
        ((key, value),) = lookup.items()
        bound = CursorBound(value=value, before=key.endswith("__lt"))
        return _FacadePageSource(self._fetch, self._ordering, bound, self._fetched)

    def __getitem__(self, items: slice) -> list[T]:
        page = self._fetch(
            CursorPageRequest(
                ordering=self._ordering, bound=self._bound, offset=items.start, limit=items.stop - items.start
            )
        )
        self._fetched.append(page)
        return page.results

    def count(self) -> int:
        return self._fetched[-1].count


class FacadeCursorPagination(StableCursorPagination):
    """Builds the cursor response from pages that a facade reads in SQL.

    The facade answers a `CursorPageRequest` with `select_cursor_page`, so cursors keep the format
    DRF gives a queryset-backed view.
    """

    def get_paginated_facade_response[T](
        self,
        request: Request,
        view: "GenericAPIView",
        fetch: Callable[[CursorPageRequest], Page[T]],
        serializer_class: type[BaseSerializer] | None = None,
    ) -> Response:
        rows = self.paginate_queryset(cast(Any, _FacadePageSource(fetch)), request, view)
        # The page size is a class attribute, so the paginator always returns a page.
        assert rows is not None

        serializer_class = serializer_class or view.get_serializer_class()
        serializer = serializer_class(rows, many=True, context=view.get_serializer_context())
        return self.get_paginated_response(serializer.data)
