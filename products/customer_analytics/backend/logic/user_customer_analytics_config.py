from collections.abc import Sequence
from uuid import UUID

from posthog.models.scoping.manager import resolve_effective_team_id

from products.customer_analytics.backend.facade.enums import AccountPropertyPinKind
from products.customer_analytics.backend.models import (
    AccountRelationshipDefinition,
    CustomPropertyDefinition,
    TargetType,
    UserCustomerAnalyticsConfig,
)

PINNED_PROPERTIES_KEY = "pinned_properties"
MAX_PINNED_PROPERTIES = 50


class InvalidPinnedAccountProperties(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def get_or_create_config(*, team_id: int, user_id: int) -> UserCustomerAnalyticsConfig:
    # Resolve an environment (child team) id to its root team once. `for_team` canonicalizes its
    # filter but not the create kwargs, so a raw id makes the lookup never match, and the unique
    # constraint then rejects every call after the first.
    canonical_team_id = resolve_effective_team_id(team_id)
    config, _ = UserCustomerAnalyticsConfig.objects.for_team(canonical_team_id, canonical=True).get_or_create(
        team_id=canonical_team_id,
        user_id=user_id,
        defaults={"properties": {PINNED_PROPERTIES_KEY: []}},
    )
    if PINNED_PROPERTIES_KEY in config.properties:
        return config

    legacy_references = [
        {"kind": AccountPropertyPinKind.CUSTOM_PROPERTY.value, "id": str(definition_id)}
        for definition_id in config.pinned_custom_property_definition_ids
    ]
    config.properties = {**config.properties, PINNED_PROPERTIES_KEY: legacy_references}
    config.save(update_fields=["properties", "updated_at"])
    return config


def update_pinned_properties(
    *, team_id: int, user_id: int, references: Sequence[tuple[AccountPropertyPinKind, UUID]]
) -> UserCustomerAnalyticsConfig:
    _validate_pinned_properties(team_id=team_id, references=references)
    config = get_or_create_config(team_id=team_id, user_id=user_id)
    config.properties = {
        **config.properties,
        PINNED_PROPERTIES_KEY: [{"kind": kind.value, "id": str(definition_id)} for kind, definition_id in references],
    }
    config.pinned_custom_property_definition_ids = [
        definition_id for kind, definition_id in references if kind == AccountPropertyPinKind.CUSTOM_PROPERTY
    ]
    config.save(update_fields=["properties", "pinned_custom_property_definition_ids", "updated_at"])
    return config


def _validate_pinned_properties(*, team_id: int, references: Sequence[tuple[AccountPropertyPinKind, UUID]]) -> None:
    if len(references) > MAX_PINNED_PROPERTIES:
        raise InvalidPinnedAccountProperties([f"Pin at most {MAX_PINNED_PROPERTIES} account properties."])

    errors: list[str] = []
    first_index_by_reference: dict[tuple[AccountPropertyPinKind, UUID], int] = {}
    for index, reference in enumerate(references):
        if reference in first_index_by_reference:
            errors.append(f"Item {index + 1} duplicates item {first_index_by_reference[reference] + 1}.")
        else:
            first_index_by_reference[reference] = index

    referenced_ids = {definition_id for _, definition_id in references}
    custom_property_targets = dict(
        CustomPropertyDefinition.objects.for_team(team_id)
        .filter(id__in=referenced_ids)
        .values_list("id", "target_type")
    )
    matching_relationship_ids = set(
        AccountRelationshipDefinition.objects.for_team(team_id)
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
