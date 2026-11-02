"""Pages a Django queryset into the `posthog.paging` types.

Logic and facade modules import it, so it imports Django only and never DRF."""

from collections.abc import Collection

from django.db.models import Model, QuerySet

from posthog.paging import CursorPageRequest, Page, PageRequest


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


def select_page[M: Model](queryset: QuerySet[M], page: PageRequest) -> Page[M]:
    """Return one page of `queryset` and the number of rows in all of it.

    The rows are also sorted by primary key, so a page boundary between rows that share a sort value
    cannot skip or repeat a row.
    """
    count = queryset.count()
    if count == 0 or page.offset >= count:
        return Page(results=[], count=count)
    rows = stable_queryset_ordering(queryset)[page.offset : page.offset + page.limit]
    return Page(results=list(rows), count=count)


def select_cursor_page[M: Model](
    queryset: QuerySet[M], page: CursorPageRequest, *, ordering_fields: Collection[str]
) -> Page[M]:
    """Return the rows of one cursor page of `queryset` and the number of rows in all of it.

    `ordering_fields` names the fields a client may sort by. The primary key is always allowed,
    because `StableCursorPagination` adds it as the last ordering term.
    """
    primary_key_names = {"pk", queryset.model._meta.pk.name}
    for term in page.ordering:
        if term.lstrip("-") not in ordering_fields and term.lstrip("-") not in primary_key_names:
            raise ValueError(f"Cannot order by {term!r}")

    count = queryset.count()
    first = page.ordering[0]
    queryset = stable_queryset_ordering(queryset.order_by(*page.ordering))
    if page.bound is not None:
        comparison = "lt" if page.bound.before else "gt"
        queryset = queryset.filter(**{f"{first.lstrip('-')}__{comparison}": page.bound.value})

    return Page(results=list(queryset[page.offset : page.offset + page.limit]), count=count)
