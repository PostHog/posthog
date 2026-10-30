import json
from base64 import b64decode, b64encode
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qs, urlencode

from django.core.exceptions import ImproperlyConfigured

from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination, LimitOffsetPagination, PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.utils.urls import remove_query_param, replace_query_param

from posthog.dataclasses import frozen
from posthog.paging import CursorPageRequest, Page, PageRequest
from posthog.queryset_paging import select_cursor_rows

if TYPE_CHECKING:
    # DRF's generics module reads DEFAULT_PAGINATION_CLASS while it loads, which can point at this module.
    from rest_framework.generics import GenericAPIView


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


class BoundedPageNumberPagination(PageNumberPagination):
    """Numbered pages with a cap on the page size that a client chooses.

    A subclass that lets clients choose the page size with `page_size_query_param` gets that size
    cut to `max_page_size`, and the schema states the maximum. A fixed `page_size` on the subclass
    is not cut.
    """

    max_page_size = 1000

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        parameters = super().get_schema_operation_parameters(view)
        for parameter in parameters:
            if parameter["name"] == self.page_size_query_param:
                parameter["schema"]["maximum"] = self.max_page_size
        return parameters


class PrecountedLimitOffsetPagination(BoundedLimitOffsetPagination):
    """Pages a queryset that the view has already bounded with LIMIT and OFFSET.

    `LimitOffsetPagination` counts with `len(queryset)` and then slices the result in Python. A
    `RawQuerySet` answers both by fetching every row, so one page costs a read of the whole result
    set. Views that page in SQL run their own count statement and hand the total over with
    `set_count`. Without a count this behaves exactly like `BoundedLimitOffsetPagination`, so a view that
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


def _reversed_ordering(ordering: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term[1:] if term.startswith("-") else f"-{term}" for term in ordering)


@frozen
class PageCursor:
    """A decoded cursor.

    The page reads the rows that sort strictly after `after` in the direction it pages, and skips
    the first `offset` of them. `reverse` pages toward the start of the list.
    """

    reverse: bool
    after: tuple[str | None, ...]
    offset: int = 0


class StableCursorPagination(CursorPagination):
    """Cursor pages with a total row order, and a `count` like the limit/offset response.

    The primary key is added as the last ordering term, in the direction of the first term, so no
    two rows sort equal. A cursor stores the value of every ordering field of the row at the edge
    of the page, and the next page starts strictly past that row. So rows that share a sort value
    cannot move a page boundary, in either direction, and no offset is needed.

    DRF's own cursor stores only the first ordering field and skips ties with an offset, which sends
    a `previous` link to the wrong rows when more rows share one value than fit on a page. Cursors
    in that format still decode, so links issued before keep working.
    """

    # A subclass can leave `count` out, because counting costs a full scan on large tables.
    include_count: bool = True
    # Breaks ties when the list has no queryset model, as for a facade list. Contracts name the primary key `id`.
    tiebreak_field = "id"
    request: Optional[Request] = None
    # The URL of the current page, which every link starts from.
    page_url = ""

    def get_ordering(self, request: Request, queryset: Any, view: Any) -> tuple[str, ...]:
        ordering = super().get_ordering(request, queryset, view)
        model = getattr(queryset, "model", None)
        primary_key = model._meta.pk.name if model is not None else self.tiebreak_field
        if any(term.lstrip("-") in {"pk", primary_key} for term in ordering):
            return ordering
        direction = "-" if ordering[0].startswith("-") else ""
        return (*ordering, f"{direction}{primary_key}")

    def position_of(self, item: Any) -> tuple[str | None, ...]:
        """Return the value of every ordering field of `item` as text, the way a cursor stores it."""
        values = []
        for term in self.ordering:
            field = term.lstrip("-")
            value = item[field] if isinstance(item, dict) else getattr(item, field)
            values.append(None if value is None else str(value))
        return tuple(values)

    def cursor_link(self, cursor: PageCursor) -> str:
        tokens: dict[str, str] = {}
        if cursor.offset:
            tokens["o"] = str(cursor.offset)
        if cursor.reverse:
            tokens["r"] = "1"
        if cursor.after:
            tokens["v"] = json.dumps(list(cursor.after), separators=(",", ":"))
            # A server that still runs DRF's paginator during a deploy reads the first field from `p`.
            if cursor.after[0] is not None:
                tokens["p"] = cursor.after[0]
        encoded = b64encode(urlencode(tokens).encode("ascii")).decode("ascii")
        return replace_query_param(self.page_url, self.cursor_query_param, encoded)

    def _decode_cursor(self, request: Request) -> PageCursor | None:
        encoded = request.query_params.get(self.cursor_query_param)
        if encoded is None:
            return None
        try:
            tokens = parse_qs(b64decode(encoded.encode("ascii")).decode("ascii"), keep_blank_values=True)
            offset = int(tokens.get("o", ["0"])[0])
            reverse = bool(int(tokens.get("r", ["0"])[0]))
            # A cursor that DRF encoded holds only the first ordering field, as `p`.
            after = json.loads(tokens["v"][0]) if "v" in tokens else tokens.get("p", [])
        except (TypeError, ValueError):
            raise NotFound(self.invalid_cursor_message)
        if offset < 0 or not isinstance(after, list) or not all(v is None or isinstance(v, str) for v in after):
            raise NotFound(self.invalid_cursor_message)
        return PageCursor(reverse=reverse, after=tuple(after), offset=min(offset, self.offset_cutoff))

    def _read_page[T](
        self, read: Callable[[CursorPageRequest], list[T]], queryset: Any, request: Request, view: Any
    ) -> list[T] | None:
        self.request = request
        self.page_size = self.get_page_size(request)
        if not self.page_size:
            return None

        self.page_url = request.build_absolute_uri()
        self.ordering = self.get_ordering(request, queryset, view)
        self.current_cursor = self._decode_cursor(request)
        start = self.current_cursor or PageCursor(reverse=False, after=())
        if len(start.after) > len(self.ordering):
            raise NotFound(self.invalid_cursor_message)

        ordering = _reversed_ordering(self.ordering) if start.reverse else self.ordering
        rows = read(
            CursorPageRequest(ordering=ordering, after=start.after, offset=start.offset, limit=self.page_size + 1)
        )
        self.page = rows[: self.page_size]
        has_more = len(rows) > self.page_size
        has_rows_before = bool(start.after) or start.offset > 0
        if start.reverse:
            self.page.reverse()
            self.has_next, self.has_previous = has_rows_before, has_more
        else:
            self.has_next, self.has_previous = has_more, has_rows_before

        if (self.has_next or self.has_previous) and self.template is not None:
            self.display_page_controls = True
        return self.page

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> Optional[list[Any]]:
        self.count_rows: Callable[[], int] = queryset.count
        return self._read_page(lambda page: select_cursor_rows(queryset, page), queryset, request, view)

    def get_next_link(self) -> Optional[str]:
        if not self.has_next:
            return None
        if not self.page:
            # No row sorts before the cursor any more, so the next page is the first page.
            return remove_query_param(self.page_url, self.cursor_query_param)
        return self.cursor_link(PageCursor(reverse=False, after=self.position_of(self.page[-1])))

    def get_previous_link(self) -> Optional[str]:
        if not self.has_previous:
            return None
        if not self.page:
            # No row sorts after the cursor any more, so the previous page is the last page.
            return self.cursor_link(PageCursor(reverse=True, after=()))
        return self.cursor_link(PageCursor(reverse=True, after=self.position_of(self.page[0])))

    def get_paginated_response(self, data: Any) -> Response:
        if not self.include_count:
            return super().get_paginated_response(data)
        return Response(
            {
                "count": self.count_rows(),
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema: dict) -> dict:
        paginated = super().get_paginated_response_schema(schema)
        if not self.include_count:
            return paginated
        paginated["required"] = ["count", "results"]
        paginated["properties"] = {
            "count": {"type": "integer", "example": 123},
            **paginated["properties"],
        }
        return paginated


class FacadeCursorPagination(StableCursorPagination):
    """Builds the cursor response from pages that a facade reads in SQL.

    The facade answers a `CursorPageRequest` with `select_cursor_page`, so its cursors work the
    same as those of a queryset-backed view. The list has no queryset model here, so the tiebreak
    is `tiebreak_field`, and every ordering field must be readable on the facade's contracts.
    """

    def get_paginated_facade_response[T](
        self,
        request: Request,
        view: "GenericAPIView",
        fetch: Callable[[CursorPageRequest], Page[T]],
        serializer_class: type[BaseSerializer] | None = None,
    ) -> Response:
        fetched: list[Page[T]] = []

        def read(page: CursorPageRequest) -> list[T]:
            fetched.append(fetch(page))
            return fetched[-1].results

        rows = self._read_page(read, None, request, view)
        # The page size is a class attribute, so the paginator always returns a page.
        assert rows is not None
        self.count_rows = lambda: fetched[-1].count

        serializer_class = serializer_class or view.get_serializer_class()
        serializer = serializer_class(rows, many=True, context=view.get_serializer_context())
        return self.get_paginated_response(serializer.data)


def facade_page_response[T](
    view: "GenericAPIView",
    fetch: Callable[[PageRequest], Page[T]],
    serializer_class: type[BaseSerializer] | None = None,
) -> Response:
    """Return the limit/offset response for one page that `fetch` reads through a facade."""
    paginator = view.paginator
    if not isinstance(paginator, FacadeLimitOffsetPagination):
        raise ImproperlyConfigured(f"{type(view).__name__} needs a FacadeLimitOffsetPagination pagination_class.")
    return paginator.get_paginated_facade_response(view.request, view, fetch, serializer_class)


def facade_cursor_page_response[T](
    view: "GenericAPIView",
    fetch: Callable[[CursorPageRequest], Page[T]],
    serializer_class: type[BaseSerializer] | None = None,
) -> Response:
    """Return the cursor response for one page that `fetch` reads through a facade."""
    paginator = view.paginator
    if not isinstance(paginator, FacadeCursorPagination):
        raise ImproperlyConfigured(f"{type(view).__name__} needs a FacadeCursorPagination pagination_class.")
    return paginator.get_paginated_facade_response(view.request, view, fetch, serializer_class)
