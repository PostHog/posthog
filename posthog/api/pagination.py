from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Optional

from django.db.models import Model, QuerySet

from rest_framework.pagination import CursorPagination, LimitOffsetPagination

if TYPE_CHECKING:
    from rest_framework.viewsets import GenericViewSet

    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


def _ordering_with_primary_key(ordering: Sequence[Any], model: type[Model]) -> tuple[Any, ...]:
    primary_key = model._meta.pk.name
    if any(str(term).lstrip("-") in {"pk", primary_key} for term in ordering):
        return tuple(ordering)

    direction = "-" if str(ordering[0]).startswith("-") else ""
    return (*ordering, f"{direction}pk")


def stable_queryset_ordering(queryset: QuerySet) -> QuerySet:
    """Add the primary key as a final ordering term for a paginated queryset."""
    if queryset.query.is_sliced or queryset.query.group_by is not None:
        return queryset

    ordering = queryset.query.order_by or queryset.query.extra_order_by or queryset.model._meta.ordering
    if not ordering:
        return queryset.order_by("pk")

    stable_ordering = _ordering_with_primary_key(ordering, queryset.model)
    if len(stable_ordering) == len(ordering):
        return queryset
    return queryset.order_by(*stable_ordering)


class StableOrderingPaginationMixin(_GenericViewSet):
    """Add the primary key as a final ordering term to each queryset that the viewset pages.

    TeamAndOrgViewSetMixin inherits this. A viewset without that mixin inherits it directly.
    """

    def paginate_queryset(self, queryset: QuerySet | Sequence) -> Sequence | None:
        if self.paginator is not None and isinstance(queryset, QuerySet):
            queryset = stable_queryset_ordering(queryset)
        return super().paginate_queryset(queryset)


class StableCursorPagination(CursorPagination):
    """Cursor pagination that adds the primary key as a final ordering term.

    The paginator replaces the queryset ordering, so `stable_queryset_ordering` cannot reach it.
    DRF positions a cursor on the first ordering field and skips the rows that tie on it by count.
    That skip is correct only when tied rows come back in the same order on every request.
    The cursor encodes only the first ordering field, so the tiebreaker does not change the cursor format.
    """

    def get_ordering(self, request, queryset, view) -> tuple[str, ...]:
        return _ordering_with_primary_key(super().get_ordering(request, queryset, view), queryset.model)


class PrecountedLimitOffsetPagination(LimitOffsetPagination):
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
