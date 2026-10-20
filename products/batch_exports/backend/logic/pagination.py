"""Read one page of an ordered list of rows, as ``contracts.ListPage`` asks for it."""

from collections.abc import Collection

from django.db.models import Model, QuerySet

from posthog.api.pagination import stable_queryset_ordering

from products.batch_exports.backend.facade import contracts


def select_page[M: Model](
    queryset: QuerySet[M], page: contracts.ListPage, *, ordering_fields: Collection[str]
) -> list[M]:
    """Return the rows of one page of ``queryset``.

    The rows are also sorted by primary key, in the direction of the first ordering field. Without
    it, rows that share a value can change places between two queries, so a page boundary between
    them can skip or repeat a row.
    """
    for term in page.ordering:
        if term.lstrip("-") not in ordering_fields:
            raise ValueError(f"Cannot order by {term!r}")

    first = page.ordering[0]
    queryset = stable_queryset_ordering(queryset.order_by(*page.ordering))

    if page.bound is not None:
        comparison = "lt" if page.bound.before else "gt"
        queryset = queryset.filter(**{f"{first.lstrip('-')}__{comparison}": page.bound.value})

    return list(queryset[page.offset : page.offset + page.limit])
