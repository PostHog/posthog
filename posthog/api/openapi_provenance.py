"""Provenance tags for OpenAPI components generated from Pydantic models.

Components that enter the spec through a Pydantic model carry an
``x-schema-source`` vendor extension naming the authoring Python class, e.g.
``posthog.schema.TrendsQuery`` or
``products.logs.backend.contracts.LogsAlertFilters``.

The tag lets downstream consumers tell the two type pipelines apart without
name matching: components sourced from ``posthog.schema`` are machine
projections of frontend-authored schema.ts types (round-trip twins that
generators may alias back to their TS source), while components sourced from
product contracts are genuinely backend-authored and should keep generating.

Root models are tagged exactly — the class object is in hand at emission.
Pydantic only exposes nested ``$defs`` by name, so those are resolved against
the root model's module and ``posthog.schema`` with a structural sanity check
(property names for models, member values for enums). When resolution fails or
is ambiguous the component is left untagged; consumers must treat a missing
tag as unknown provenance, never as a third state.
"""

import sys
from enum import Enum
from typing import Any

from pydantic import BaseModel

SCHEMA_SOURCE_KEY = "x-schema-source"


def schema_source_path(source: type) -> str:
    return f"{source.__module__}.{source.__qualname__}"


def _structurally_matches(candidate: type, def_schema: dict[str, Any]) -> bool:
    if not isinstance(candidate, type):
        return False
    if issubclass(candidate, BaseModel):
        properties = def_schema.get("properties")
        if properties is None:
            return False
        field_names = {
            field.serialization_alias or field.alias or name for name, field in candidate.model_fields.items()
        }
        return set(properties) == field_names
    if issubclass(candidate, Enum):
        enum_values = def_schema.get("enum")
        if enum_values is None:
            return False
        return {member.value for member in candidate} == set(enum_values)
    return False


def resolve_def_class(def_name: str, def_schema: dict[str, Any], root_model: type[BaseModel]) -> type | None:
    """Resolve a pydantic ``$defs`` entry back to its authoring class.

    Candidates, in priority order: the root model's own module (nested product
    contract types), then ``posthog.schema`` (the kernel). A candidate only
    counts when its structure matches the def schema, so a coincidental name
    collision yields no tag instead of a wrong one.
    """
    import posthog.schema as kernel_schema  # noqa: PLC0415 — keeps the 28k-line schema module off this module's import path

    root_module = sys.modules.get(root_model.__module__)
    for module in (root_module, kernel_schema):
        if module is None:
            continue
        candidate = getattr(module, def_name, None)
        if candidate is not None and _structurally_matches(candidate, def_schema):
            return candidate
    return None


def tag_components_from_model(components: dict[str, dict[str, Any]], root_model: type[BaseModel]) -> None:
    """Stamp ``x-schema-source`` on components hoisted from ``root_model``'s JSON schema."""
    for name, schema in components.items():
        if name == root_model.__name__:
            schema[SCHEMA_SOURCE_KEY] = schema_source_path(root_model)
            continue
        resolved = resolve_def_class(name, schema, root_model)
        if resolved is not None:
            schema[SCHEMA_SOURCE_KEY] = schema_source_path(resolved)
