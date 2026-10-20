from collections.abc import Sequence
from uuid import UUID

from posthog.models.scoping.manager import resolve_effective_team_id

from products.customer_analytics.backend.facade.contracts import InvalidPinnedAccountProperties
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.models import (
    AccountRelationshipDefinition,
    CustomPropertyDefinition,
    TargetType,
)

MAX_PINNED_PROPERTIES = 50


def validate_pinned_properties(*, team_id: int, references: Sequence[tuple[AccountPropertyPinKind, UUID]]) -> None:
    if len(references) > MAX_PINNED_PROPERTIES:
        raise InvalidPinnedAccountProperties([f"Pin at most {MAX_PINNED_PROPERTIES} account properties."])

    errors: list[str] = []
    first_index_by_reference: dict[tuple[AccountPropertyPinKind, UUID], int] = {}
    for index, reference in enumerate(references):
        if reference in first_index_by_reference:
            errors.append(f"Item {index + 1} duplicates item {first_index_by_reference[reference] + 1}.")
        else:
            first_index_by_reference[reference] = index

    canonical_team_id = resolve_effective_team_id(team_id)
    referenced_ids = {definition_id for _, definition_id in references}
    custom_property_targets = dict(
        CustomPropertyDefinition.objects.for_team(canonical_team_id)
        .filter(id__in=referenced_ids)
        .values_list("id", "target_type")
    )
    matching_relationship_ids = set(
        AccountRelationshipDefinition.objects.for_team(canonical_team_id)
        .filter(id__in=referenced_ids)
        .values_list("id", flat=True)
    )

    for index, (kind, definition_id) in enumerate(references):
        item = index + 1
        if kind == AccountPropertyPinKind.CUSTOM_PROPERTY:
            target_type = custom_property_targets.get(definition_id)
            if target_type is not None:
                if target_type != TargetType.ACCOUNT.value:
                    errors.append(f"Item {item} must reference an account property.")
            elif definition_id in matching_relationship_ids:
                errors.append(f"Item {item} is a relationship, not a custom property.")
            else:
                errors.append(f"Item {item} custom property was not found in this project.")
        elif definition_id in matching_relationship_ids:
            continue
        elif definition_id in custom_property_targets:
            errors.append(f"Item {item} is a custom property, not a relationship.")
        else:
            errors.append(f"Item {item} relationship was not found in this project.")

    if errors:
        raise InvalidPinnedAccountProperties(errors)
