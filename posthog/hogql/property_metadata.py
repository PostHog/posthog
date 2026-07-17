"""Property-definition metadata for HogQL property-type resolution.

`PropertyMetadata` is the plain data bundle the engine consumes; `load_property_metadata` is its
Django-side loader. The ORM reads stay behind the function call (the `Database.create_for`
pattern), so this module imports without booting Django (no settings or app registry).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


@dataclass(frozen=True)
class PropertyMetadata:
    """Property-definition types for the properties a query touches.

    Values are `{"type": <PropertyType value>}` dicts, plus a `"dmat"` key when a READY
    materialized-column slot backs an event property. Group keys are `"{group_type_index}_{name}"`.
    """

    event_properties: dict[str, dict[str, str | None]] = field(default_factory=dict)
    person_properties: dict[str, dict[str, str | None]] = field(default_factory=dict)
    group_properties: dict[str, dict[str, str | None]] = field(default_factory=dict)


def load_property_metadata(
    context: "HogQLContext",
    *,
    event_property_names: set[str],
    person_property_names: set[str],
    group_property_names: dict[int, set[str]],
) -> PropertyMetadata:
    """Fetch property-definition types for the given property names from Postgres.

    Sets `context.team` when only `team_id` was provided. Callers keep the result on
    `context.property_metadata` so downstream transforms read it without touching the ORM.
    """
    # Deferred: this function is the Django boundary of property-type resolution — keeping the ORM
    # imports behind the call is what lets the module (and its importers) load without django.setup().
    from django.db import models  # noqa: PLC0415
    from django.db.models.functions.comparison import Coalesce  # noqa: PLC0415

    from posthog.clickhouse.materialized_columns import DMAT_STRING_COLUMN_NAME_PREFIX  # noqa: PLC0415
    from posthog.models import PropertyDefinition, Team  # noqa: PLC0415
    from posthog.models.materialized_column_slots import (  # noqa: PLC0415
        MaterializedColumnSlot,
        MaterializedColumnSlotState,
    )

    team_id = context.team_id
    if team_id is None:
        raise ValueError("load_property_metadata requires a context with team_id set")

    if not context.team:
        context.team = Team.objects.get(id=team_id)

    # Load event property definitions with their materialized slots in a single query
    event_property_definitions = (
        PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        )
        .filter(
            effective_project_id=context.team.project_id,
            name__in=event_property_names,
            type__in=[None, PropertyDefinition.Type.EVENT],
        )
        .prefetch_related(
            models.Prefetch(
                "materialized_column_slots",
                queryset=MaterializedColumnSlot.objects.filter(
                    team_id=team_id, state=MaterializedColumnSlotState.READY
                ),
            )
        )
        if event_property_names
        else []
    )

    type_overrides = context.property_type_overrides or {}

    event_properties: dict[str, dict[str, str | None]] = {}
    for prop_def in event_property_definitions:
        if not prop_def.property_type:
            continue

        prop_type = type_overrides.get(prop_def.name, prop_def.property_type)
        prop_info: dict[str, str | None] = {"type": prop_type}
        slot = prop_def.materialized_column_slots.first()
        if slot:
            prop_info["dmat"] = f"{DMAT_STRING_COLUMN_NAME_PREFIX}{slot.slot_index}"

        event_properties[prop_def.name] = prop_info

    person_property_values = (
        PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        )
        .filter(
            effective_project_id=context.team.project_id,
            name__in=person_property_names,
            type=PropertyDefinition.Type.PERSON,
        )
        .values_list("name", "property_type")
        if person_property_names
        else []
    )
    person_properties: dict[str, dict[str, str | None]] = {
        name: {"type": property_type} for name, property_type in person_property_values if property_type
    }

    group_properties: dict[str, dict[str, str | None]] = {}
    for group_id, properties in group_property_names.items():
        if not properties:
            continue
        group_property_values = (
            PropertyDefinition.objects.alias(
                effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
            )
            .filter(
                effective_project_id=context.team.project_id,
                name__in=properties,
                type=PropertyDefinition.Type.GROUP,
                group_type_index=group_id,
            )
            .values_list("name", "property_type")
        )
        group_properties.update(
            {
                f"{group_id}_{name}": {"type": property_type}
                for name, property_type in group_property_values
                if property_type
            }
        )

    return PropertyMetadata(
        event_properties=event_properties,
        person_properties=person_properties,
        group_properties=group_properties,
    )
