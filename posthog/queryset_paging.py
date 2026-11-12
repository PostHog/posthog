"""Pages a Django queryset into the `posthog.paging` types.

Logic and facade modules import it, so it imports Django only and never DRF."""

from collections.abc import Collection, Sequence

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Field, Model, Q, QuerySet

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


def select_page_without_count[M: Model](queryset: QuerySet[M], page: PageRequest) -> Page[M]:
    """Return one page of `queryset` without counting the whole list, for filters too costly to run twice.

    It reads one row past the page to learn whether another page follows. `count` then holds the rows
    through this page, plus one when another page follows, so that a limit/offset paginator sets `next`
    exactly when more rows exist.
    """
    rows = list(stable_queryset_ordering(queryset)[page.offset : page.offset + page.limit + 1])
    more = len(rows) > page.limit
    results = rows[: page.limit]
    return Page(results=results, count=page.offset + len(results) + (1 if more else 0))


def _model_field(model: type[Model], field: str) -> Field | None:
    """Return the column field that `field` names, or None for an annotation or a relation without a column."""
    if field == "pk":
        return model._meta.pk
    try:
        model_field = model._meta.get_field(field)
    except FieldDoesNotExist:
        return None
    return model_field if isinstance(model_field, Field) else None


def _is_nullable(model: type[Model], field: str) -> bool:
    model_field = _model_field(model, field)
    # An annotation, a reverse relation or a generic key can hold NULL, and nothing here tells otherwise.
    return True if model_field is None else model_field.null


def _cursor_value(model: type[Model], field: str, value: str | None) -> object:
    """Convert a cursor value from text to the type of its field.

    A value the field cannot hold, such as "abc" for an integer, raises Django's ValidationError.
    """
    if value is None:
        return None
    model_field = _model_field(model, field)
    if model_field is None:
        return value
    return model_field.to_python(value)


def _sorts_after(field: str, value: object, *, descending: bool, nullable: bool) -> Q | None:
    """Match the rows whose `field` alone sorts after `value`, or return None when no row can.

    Postgres sorts NULL after every value in ascending order and before every value in descending
    order, and `value` is None for a NULL.
    """
    if value is None:
        return Q(**{f"{field}__isnull": False}) if descending else None
    if descending:
        return Q(**{f"{field}__lt": value})
    if nullable:
        return Q(**{f"{field}__gt": value}) | Q(**{f"{field}__isnull": True})
    return Q(**{f"{field}__gt": value})


def _rows_after(model: type[Model], ordering: Sequence[str], after: Sequence[str | None]) -> Q:
    """Match the rows that sort strictly after the row whose leading ordering fields hold `after`.

    For the ordering `(a, -b)` this is `a > x OR (a = x AND b < y)`. A cursor that DRF encoded
    holds only the first field, so the match then compares that field alone.
    """
    # Starts as a match for no row, and each field adds one more way to sort after the cursor row.
    rows_after = Q(pk__in=[])
    ties = Q()
    values = [_cursor_value(model, term.lstrip("-"), value) for term, value in zip(ordering, after)]
    for term, value in zip(ordering, values):
        field = term.lstrip("-")
        descending = term.startswith("-")
        sorts_after = _sorts_after(field, value, descending=descending, nullable=_is_nullable(model, field))
        if sorts_after is not None:
            rows_after |= ties & sorts_after
        ties &= Q(**{f"{field}__isnull": True}) if value is None else Q(**{field: value})

    first = ordering[0].lstrip("-")
    if len(after) < 2 or values[0] is None or _is_nullable(model, first):
        return rows_after
    # The first field's own bound repeats part of the match, so that an index on that field can limit the scan.
    bound = "lte" if ordering[0].startswith("-") else "gte"
    return Q(**{f"{first}__{bound}": values[0]}) & rows_after


def select_cursor_rows[M: Model](queryset: QuerySet[M], page: CursorPageRequest) -> list[M]:
    """Return the rows of one cursor page of `queryset`, without counting the whole list."""
    queryset = stable_queryset_ordering(queryset.order_by(*page.ordering))
    if page.after:
        queryset = queryset.filter(_rows_after(queryset.model, page.ordering, page.after))
    return list(queryset[page.offset : page.offset + page.limit])


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
    return Page(results=select_cursor_rows(queryset, page), count=count)
