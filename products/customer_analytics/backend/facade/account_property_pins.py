from collections.abc import Sequence
from typing import cast

from products.customer_analytics.backend.facade.contracts import (
    InvalidPinnedAccountProperties,
    PinnedAccountProperty,
    PinnedAccountPropertyKind,
)
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.logic.account_property_pins import validate_pinned_properties


def validate_pinned_account_properties(
    *, team_id: int, pinned_properties: Sequence[PinnedAccountProperty]
) -> list[PinnedAccountProperty]:
    references = validate_pinned_properties(
        team_id=team_id,
        references=[(AccountPropertyPinKind(reference.kind), reference.id) for reference in pinned_properties],
    )
    return [
        PinnedAccountProperty(kind=cast(PinnedAccountPropertyKind, kind.value), id=reference_id)
        for kind, reference_id in references
    ]


__all__ = ["InvalidPinnedAccountProperties", "validate_pinned_account_properties"]
