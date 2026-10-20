from collections.abc import Sequence

from products.customer_analytics.backend.facade.contracts import InvalidPinnedAccountProperties, PinnedAccountProperty
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.logic.account_property_pins import validate_pinned_properties


def validate_pinned_account_properties(*, team_id: int, pinned_properties: Sequence[PinnedAccountProperty]) -> None:
    validate_pinned_properties(
        team_id=team_id,
        references=[(AccountPropertyPinKind(reference.kind), reference.id) for reference in pinned_properties],
    )


__all__ = ["InvalidPinnedAccountProperties", "validate_pinned_account_properties"]
