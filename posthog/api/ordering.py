from collections.abc import Sequence

from rest_framework import filters


class StableOrderingFilter(filters.OrderingFilter):
    """`OrderingFilter` that appends `id` to every ordering, so tied rows keep one fixed position.

    Limit-offset pagination runs a separate query for each page. When the sort columns hold the
    same value on several rows, Postgres is free to return those rows in a different order on
    each query, so a tied row can land on two pages, or on no page at all. A unique last key
    removes that freedom.
    """

    def get_ordering(self, request, queryset, view) -> Sequence[str] | None:
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        return [*ordering, "-id" if ordering[-1].startswith("-") else "id"]
