from collections.abc import Sequence
from uuid import UUID

from django.db.models import Model, QuerySet


def rows_in_id_order[M: Model](queryset: QuerySet[M], ids: Sequence[UUID]) -> list[M]:
    """Load the rows of `queryset` with these ids, in the order of `ids`."""
    by_id = {row.pk: row for row in queryset.filter(pk__in=ids)}
    return [by_id[row_id] for row_id in ids if row_id in by_id]
