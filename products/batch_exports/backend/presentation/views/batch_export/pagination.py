"""Cursor pagination over lists that the facade reads."""

from collections.abc import Callable
from typing import Any, cast

from rest_framework.generics import GenericAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from products.batch_exports.backend.facade import contracts


# TODO: Nothing here is specific to batch exports. Move it to posthog/api/pagination.py with
# select_page in logic/pagination.py, and a core page type to replace contracts.ListPage, so other
# facade-backed products can page with a cursor too.
class _FacadePageSource[T]:
    """Stands in for the queryset that ``CursorPagination.paginate_queryset`` pages through.

    The paginator only orders the queryset, filters it on the cursor position and slices it.
    This records the ordering and the position, and the slice reads that page through the
    facade. So DRF still decodes and encodes every cursor, and the cursors stay the same.
    """

    def __init__(
        self,
        fetch: Callable[[contracts.ListPage], list[T]],
        ordering: tuple[str, ...] = (),
        bound: contracts.ListPageBound | None = None,
    ) -> None:
        self._fetch = fetch
        self._ordering = ordering
        self._bound = bound

    def order_by(self, *ordering: str) -> "_FacadePageSource[T]":
        return _FacadePageSource(self._fetch, ordering, self._bound)

    def filter(self, **lookup: str) -> "_FacadePageSource[T]":
        # The only filter is the position, as `<first ordering field>__lt` or `__gt`.
        ((key, value),) = lookup.items()
        bound = contracts.ListPageBound(value=value, before=key.endswith("__lt"))
        return _FacadePageSource(self._fetch, self._ordering, bound)

    def __getitem__(self, items: slice) -> list[T]:
        page = contracts.ListPage(
            ordering=self._ordering, bound=self._bound, offset=items.start, limit=items.stop - items.start
        )
        return self._fetch(page)


class FacadeCursorPagination(CursorPagination):
    def get_paginated_facade_response[T](
        self, request: Request, view: GenericAPIView, fetch: Callable[[contracts.ListPage], list[T]]
    ) -> Response:
        """Return the page the request asks for, serialized by the view. ``fetch`` reads a page through the facade."""
        page = self.paginate_queryset(cast(Any, _FacadePageSource(fetch)), request, view)
        # The page size is a class attribute, so the paginator always returns a page.
        assert page is not None
        return self.get_paginated_response(view.get_serializer(page, many=True).data)
