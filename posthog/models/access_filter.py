"""Apply an authz `AccessFilter` to a Django QuerySet.

The access_filter carries the decision; this module only translates it. It knows the column names,
which the authz facade must not, so it lives next to the ORM instead of inside the product.
"""

from typing import TypeVar

from django.db.models import Model, Q, QuerySet

from products.authz.backend.facade.contracts import AccessFilter
from products.authz.backend.facade.enums import FilterKind

M = TypeVar("M", bound=Model)


def apply_filter(
    queryset: QuerySet[M],
    access_filter: AccessFilter,
    *,
    id_field: str = "id",
    creator_field: str | None = "created_by",
    subject_user_id: int | None = None,
) -> QuerySet[M]:
    """Narrow `queryset` to the rows `access_filter` allows.

    The creator exemption applies only when the filter asks for it, the model has `creator_field`,
    and the subject is a user. A NONE filter with the exemption still returns the subject's own rows.
    """
    creator: Q | None = None
    if access_filter.creator_exempt and creator_field and subject_user_id is not None:
        creator = Q(**{creator_field: subject_user_id})

    if access_filter.kind == FilterKind.ALL:
        return queryset
    if access_filter.kind == FilterKind.NONE:
        return queryset.filter(creator) if creator else queryset.none()

    # nosemgrep: orm-field-injection id_field is a column name the calling code names, never request input
    ids = Q(**{f"{id_field}__in": access_filter.ids})
    if access_filter.kind == FilterKind.ONLY:
        return queryset.filter(ids | creator if creator else ids)
    return queryset.exclude(ids & ~creator if creator else ids)
