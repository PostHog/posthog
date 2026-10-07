from collections.abc import Sequence
from uuid import UUID

from posthog.models.scoping.manager import resolve_effective_team_id

from products.customer_analytics.backend.facade.contracts import AccountTableField, InvalidPinnedAccountProperties
from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.models import (
    AccountRelationshipDefinition,
    CustomPropertyDefinition,
    TargetType,
)

MAX_PINNED_PROPERTIES = 50
PINNABLE_ACCOUNT_FIELDS = frozenset({AccountTableField.STRIPE_CUSTOMER_ID.value})


def _parse_definition_id(reference_id: str) -> UUID | None:
    try:
        return UUID(reference_id)
    except ValueError:
        return None


def validate_pinned_properties(
    *, team_id: int, references: Sequence[tuple[AccountPropertyPinKind, str]]
) -> list[tuple[AccountPropertyPinKind, str]]:
    """Validate the references and return them with definition UUIDs in canonical form."""
    if len(references) > MAX_PINNED_PROPERTIES:
        raise InvalidPinnedAccountProperties([f"Pin at most {MAX_PINNED_PROPERTIES} account properties."])

    definition_ids: dict[int, UUID] = {}
    normalized: list[tuple[AccountPropertyPinKind, str]] = []
    for index, (kind, reference_id) in enumerate(references):
        definition_id = None if kind == AccountPropertyPinKind.ACCOUNT_FIELD else _parse_definition_id(reference_id)
        if definition_id is not None:
            definition_ids[index] = definition_id
        normalized.append((kind, str(definition_id) if definition_id is not None else reference_id))

    errors: list[str] = []
    first_index_by_reference: dict[tuple[AccountPropertyPinKind, str], int] = {}
    for index, reference in enumerate(normalized):
        if reference in first_index_by_reference:
            errors.append(f"Item {index + 1} duplicates item {first_index_by_reference[reference] + 1}.")
        else:
            first_index_by_reference[reference] = index

    canonical_team_id = resolve_effective_team_id(team_id)
    referenced_ids = set(definition_ids.values())
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

    for index, (kind, reference_id) in enumerate(normalized):
        item = index + 1
        if kind == AccountPropertyPinKind.ACCOUNT_FIELD:
            if reference_id not in PINNABLE_ACCOUNT_FIELDS:
                errors.append(f"Item {item} is not an account field that can be pinned.")
            continue
        definition_id = definition_ids.get(index)
        if definition_id is None:
            errors.append(f"Item {item} must reference a definition by UUID.")
        elif kind == AccountPropertyPinKind.CUSTOM_PROPERTY:
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
    return normalized
