from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import MutableMapping
from typing import Any, TypedDict

from drf_spectacular.plumbing import list_hash, load_enum_name_overrides
from drf_spectacular.settings import spectacular_settings


class EnumCollision(TypedDict):
    field: str
    auto_name: str
    hash: str
    values: list[Any]
    has_spec_id: bool
    inline_override_matches: bool
    components: list[tuple[str, str]]


def _camelize(s: str) -> str:
    return "".join(part.capitalize() for part in s.split("_"))


def _iter_prop_containers(schema: Any, component_name: str | None = None) -> Any:
    """Walk OpenAPI component schemas yielding (component_name, properties) pairs.

    Copied from the nested function inside drf_spectacular.hooks.postprocess_schema_enums.
    """
    if not component_name:
        for comp_name, comp_schema in schema.items():
            if spectacular_settings.COMPONENT_SPLIT_PATCH:
                comp_name = re.sub(r"^Patched(.+)", r"\1", comp_name)
            if spectacular_settings.COMPONENT_SPLIT_REQUEST:
                comp_name = re.sub(r"(.+)Request$", r"\1", comp_name)
            yield from _iter_prop_containers(comp_schema, comp_name)
    elif isinstance(schema, list):
        for item in schema:
            yield from _iter_prop_containers(item, component_name)
    elif isinstance(schema, dict):
        if schema.get("properties"):
            yield component_name, schema["properties"]
        yield from _iter_prop_containers(schema.get("oneOf", []), component_name)
        yield from _iter_prop_containers(schema.get("allOf", []), component_name)
        yield from _iter_prop_containers(schema.get("anyOf", []), component_name)


def _collect_enum_metadata(
    schemas: dict[str, Any],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[tuple[str, str]]],
    dict[str, list[Any]],
    dict[str, bool],
]:
    prop_hash_mapping: dict[str, set[str]] = defaultdict(set)
    hash_name_mapping: dict[str, set[tuple[str, str]]] = defaultdict(set)
    hash_values: dict[str, list[Any]] = {}
    hash_has_spec_id: dict[str, bool] = {}

    for component_name, props in _iter_prop_containers(schemas):
        for prop_name, prop_schema in props.items():
            ps = prop_schema
            if ps.get("type") == "array":
                ps = ps.get("items", {})
            if not isinstance(ps, MutableMapping) or "enum" not in ps:
                continue

            if "x-spec-enum-id" in ps:
                h = ps["x-spec-enum-id"]
                hash_has_spec_id[h] = True
            else:
                h = list_hash([(i, i) for i in ps["enum"] if i not in ("", None)])
                hash_has_spec_id[h] = False

            prop_hash_mapping[prop_name].add(h)
            hash_name_mapping[h].add((component_name, prop_name))
            hash_values[h] = ps["enum"]

    return prop_hash_mapping, hash_name_mapping, hash_values, hash_has_spec_id


def collect_enum_hashes(schemas: dict[str, Any]) -> set[str]:
    prop_hash_mapping, _, _, _ = _collect_enum_metadata(schemas)
    all_hashes: set[str] = set()
    for prop_hashes in prop_hash_mapping.values():
        all_hashes.update(prop_hashes)
    return all_hashes


def find_unresolved_enum_collisions(schemas: dict[str, Any]) -> list[EnumCollision]:
    overrides = load_enum_name_overrides()
    enum_suffix = spectacular_settings.ENUM_SUFFIX

    prop_hash_mapping, hash_name_mapping, hash_values, hash_has_spec_id = _collect_enum_metadata(schemas)

    collisions: list[EnumCollision] = []
    for prop_name, prop_hash_set in prop_hash_mapping.items():
        for prop_hash in prop_hash_set:
            if prop_hash in overrides:
                continue
            if len(prop_hash_set) == 1:
                continue
            if len(hash_name_mapping[prop_hash]) == 1:
                continue
            auto_name = f"{_camelize(prop_name)}{prop_hash[:3].capitalize()}{enum_suffix}"
            values = hash_values[prop_hash]
            # Even ChoiceField gets x-spec-enum-id, but if the field was built from a
            # plain list (`choices=["A", "B"]`) DRF expands it to (value, value) pairs
            # — same hash as the inline-list override path. The model-class-path
            # override is only required when labels differ from values (typical
            # `TextChoices` with explicit labels).
            inline_override_hash = list_hash([(v, v) for v in values if v not in ("", None)])
            inline_override_matches = inline_override_hash == prop_hash
            collisions.append(
                {
                    "field": prop_name,
                    "auto_name": auto_name,
                    "hash": prop_hash,
                    "values": values,
                    "has_spec_id": hash_has_spec_id[prop_hash],
                    "inline_override_matches": inline_override_matches,
                    "components": sorted(hash_name_mapping[prop_hash]),
                }
            )

    return collisions
