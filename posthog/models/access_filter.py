"""Apply an authz `ObjectIds` result to a Django QuerySet.

The result carries the decision; this module only translates it. It knows the column names,
which the authz facade must not, so it lives next to the ORM instead of inside the product.
"""

from django.db.models import Q

from products.authz.backend.facade.contracts import ObjectIds


def object_ids_to_q(
    result: ObjectIds,
    *,
    id_field: str = "id",
    creator_field: str | None = "created_by",
    subject_user_id: int | None = None,
) -> Q:
    """The condition that keeps the rows `result` allows.

    The creator exemption applies only when the result asks for it, the model has `creator_field`,
    and the subject is a user. A result that allows nothing still keeps the subject's own rows then.
    """
    if not result.complete:
        return Q(pk__in=[])
    creator: Q | None = None
    if result.creator_exempt and creator_field and subject_user_id is not None:
        creator = Q(**{creator_field: subject_user_id})
    # nosemgrep: orm-field-injection id_field is a column name the calling code names, never request input
    ids = Q(**{f"{id_field}__in": result.ids})
    allowed = ~ids if result.excluded else ids
    return allowed | creator if creator else allowed
