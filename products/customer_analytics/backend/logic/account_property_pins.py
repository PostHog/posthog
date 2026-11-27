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
# Every native field the accounts list offers as a column can also be pinned.
PINNABLE_ACCOUNT_FIELDS = frozenset(field.value for field in AccountTableField)


def _parse_definition_id(reference_id: str) -> UUID | None:
    try:
        return UUID(reference_id)
    except ValueError:
        return None


def _parse_references(
    references: Sequence[tuple[AccountPropertyPinKind, str]],
) -> tuple[dict[int, UUID], list[tuple[AccountPropertyPinKind, str]]]:
    if len(references) > MAX_PINNED_PROPERTIES:
        raise InvalidPinnedAccountProperties([f"Pin at most {MAX_PINNED_PROPERTIES} account properties."])

    definition_ids: dict[int, UUID] = {}
    normalized: list[tuple[AccountPropertyPinKind, str]] = []
    for index, (kind, reference_id) in enumerate(references):
        definition_id = None if kind == AccountPropertyPinKind.ACCOUNT_FIELD else _parse_definition_id(reference_id)
        if definition_id is not None:
            definition_ids[index] = definition_id
        normalized.append((kind, str(definition_id) if definition_id is not None else reference_id))
    return definition_ids, normalized


def _load_definition_metadata(*, team_id: int, referenced_ids: set[UUID]) -> tuple[dict[UUID, str], set[UUID]]:
    if not referenced_ids:
        return {}, set()
    canonical_team_id = resolve_effective_team_id(team_id)
    custom_property_targets = dict(
        CustomPropertyDefinition.objects.for_team(canonical_team_id, canonical=True)
        .filter(id__in=referenced_ids)
        .values_list("id", "target_type")
    )
    matching_relationship_ids = set(
        AccountRelationshipDefinition.objects.for_team(canonical_team_id, canonical=True)
        .filter(id__in=referenced_ids)
        .values_list("id", flat=True)
    )
    return custom_property_targets, matching_relationship_ids


def _validate_parsed_references(
    *,
    definition_ids: dict[int, UUID],
    normalized: list[tuple[AccountPropertyPinKind, str]],
    custom_property_targets: dict[UUID, str],
    matching_relationship_ids: set[UUID],
) -> list[tuple[AccountPropertyPinKind, str]]:
    errors: list[str] = []
    first_index_by_reference: dict[tuple[AccountPropertyPinKind, str], int] = {}
    for index, reference in enumerate(normalized):
        if reference in first_index_by_reference:
            errors.append(f"Item {index + 1} duplicates item {first_index_by_reference[reference] + 1}.")
        else:
            first_index_by_reference[reference] = index

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


def validate_pinned_property_lists(
    *, team_id: int, reference_lists: Sequence[Sequence[tuple[AccountPropertyPinKind, str]]]
) -> list[list[tuple[AccountPropertyPinKind, str]]]:
    """Validate multiple pin lists in one metadata lookup and return canonical definition UUIDs."""
    parsed = [_parse_references(references) for references in reference_lists]
    referenced_ids = {definition_id for definition_ids, _ in parsed for definition_id in definition_ids.values()}
    custom_property_targets, matching_relationship_ids = _load_definition_metadata(
        team_id=team_id,
        referenced_ids=referenced_ids,
    )
    return [
        _validate_parsed_references(
            definition_ids=definition_ids,
            normalized=normalized,
            custom_property_targets=custom_property_targets,
            matching_relationship_ids=matching_relationship_ids,
        )
        for definition_ids, normalized in parsed
    ]


def validate_pinned_properties(
    *, team_id: int, references: Sequence[tuple[AccountPropertyPinKind, str]]
) -> list[tuple[AccountPropertyPinKind, str]]:
    """Validate the references and return them with definition UUIDs in canonical form."""
    return validate_pinned_property_lists(team_id=team_id, reference_lists=[references])[0]
