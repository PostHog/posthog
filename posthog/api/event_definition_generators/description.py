"""Generator inputs from a stack description instead of the database.

A stack's description (what `hog check` evaluates a `.ph` folder into) declares events and
their property groups. This turns those resources into what every `EventDefinitionGenerator` takes, so
the Go, Python and TypeScript modules can be generated for a stack that has never been pushed.
"""

import copy
from collections.abc import Mapping
from typing import Any, cast

from posthog.dataclasses import frozen

from .base import EventDefinitionGenerator


@frozen
class DescribedEvent:
    # The generators key `schema_map` by `str(event.id)`. A described event has no database id yet,
    # so its name, which is unique among events, stands in.
    id: str
    name: str
    description: str | None

    @property
    def doc_comment(self) -> str | None:
        return self.description or None


@frozen
class DescribedProperty:
    name: str
    property_type: str
    is_required: bool
    is_optional_in_types: bool
    description: str
    # The members of an enum property. The schema API has no field for them, so only a description
    # carries them.
    enum: tuple[str, ...] | None

    @property
    def doc_comment(self) -> str | None:
        return self.description or None


@frozen
class DescribedSchema:
    # Sorted by name, as the generators get them from the database.
    event_definitions: list[DescribedEvent]
    schema_map: dict[str, list[DescribedProperty]]


def _resources(description: Mapping[str, Any], kind: str) -> dict[str, Mapping[str, Any]]:
    return {
        resource["key"]: resource["body"]
        for resource in description.get("resources", [])
        if resource.get("kind") == kind
    }


def _property(raw: Mapping[str, Any]) -> DescribedProperty:
    members = raw.get("enum")
    return DescribedProperty(
        name=raw["name"],
        property_type=raw["property_type"],
        is_required=bool(raw.get("is_required", False)),
        is_optional_in_types=bool(raw.get("is_optional_in_types", False)),
        description=raw.get("description") or "",
        enum=tuple(members) if members is not None else None,
    )


def schema_from_description(description: Mapping[str, Any]) -> DescribedSchema:
    """The `event` and `property_group` resources of a description, as generator inputs.

    An event's properties are those of every property group it refers to, in the order it lists them,
    each group's properties sorted by name as the database orders them.
    """
    groups = _resources(description, "property_group")
    events = _resources(description, "event")
    event_definitions: list[DescribedEvent] = []
    schema_map: dict[str, list[DescribedProperty]] = {}
    for name in sorted(events):
        body = events[name]
        event = DescribedEvent(id=name, name=body.get("name", name), description=body.get("description"))
        event_definitions.append(event)
        properties: list[DescribedProperty] = []
        for ref in body.get("property_groups", []):
            target = ref.get("$ref", {}) if isinstance(ref, Mapping) else {}
            group = groups.get(str(target.get("key"))) if target.get("kind") == "property_group" else None
            if group is None:
                raise ValueError(f"The event {name} refers to a property group the description doesn't hold: {ref!r}")
            properties.extend(_property(raw) for raw in sorted(group.get("properties", []), key=lambda p: p["name"]))
        if properties:
            schema_map[event.id] = properties
    return DescribedSchema(event_definitions=event_definitions, schema_map=schema_map)


def generate_from_description(generator: EventDefinitionGenerator, description: Mapping[str, Any]) -> str:
    """The module `generator` writes for the events a description declares."""
    schema = schema_from_description(description)
    stamped = copy.copy(generator)
    stamped.generated_at = f"stack definitions, schema {schema_hash_from_description(generator, description)}"
    # The generators read only `id` and `name` of an event and the property fields above, which the
    # described types provide; they are typed for the database models they usually get.
    return stamped.generate(cast(Any, schema.event_definitions), cast(Any, schema.schema_map))


def schema_hash_from_description(generator: EventDefinitionGenerator, description: Mapping[str, Any]) -> str:
    """The hash `hog schema status` compares, for the events a description declares."""
    schema = schema_from_description(description)
    return generator.calculate_schema_hash(cast(Any, schema.event_definitions), cast(Any, schema.schema_map))
