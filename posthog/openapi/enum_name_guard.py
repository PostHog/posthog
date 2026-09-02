"""Fail schema generation when two different choice sets get one component name.

postprocess_schema_enums replaces each enum property with a reference to a
component named for the property's choice-set hash. When two different hashes
end up with the same name, the component registry keeps the first schema and
drops the second one without a warning: the second property then references
an enum with the wrong values. drf-spectacular never reports this, so these
two hooks make it loud. record_enum_hashes runs before the enum hook and
remembers the hash each property carries; check_enum_name_clashes runs right
after it, resolves the component each of those properties references now, and
raises when one component name serves two different hashes.
"""

from collections import defaultdict
from typing import Any

from posthog.openapi.enum_collisions import _collect_enum_metadata, _iter_prop_containers

_RECORDED_ATTR = "_posthog_enum_prop_hashes"
_VALUES_ATTR = "_posthog_enum_hash_values"


def record_enum_hashes(result: dict[str, Any], generator: Any, request: Any, public: bool) -> dict[str, Any]:
    schemas = result.get("components", {}).get("schemas", {})
    _, hash_name_mapping, hash_values, _ = _collect_enum_metadata(schemas)
    prop_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for enum_hash, locations in hash_name_mapping.items():
        for location in locations:
            prop_hashes[location].add(enum_hash)
    setattr(generator, _RECORDED_ATTR, dict(prop_hashes))
    setattr(generator, _VALUES_ATTR, hash_values)
    return result


def check_enum_name_clashes(result: dict[str, Any], generator: Any, request: Any, public: bool) -> dict[str, Any]:
    recorded: dict[tuple[str, str], set[str]] | None = getattr(generator, _RECORDED_ATTR, None)
    if recorded is None:
        return result
    hash_values: dict[str, list[Any]] = getattr(generator, _VALUES_ATTR, {})

    name_hashes: dict[str, set[str]] = defaultdict(set)
    schemas = result.get("components", {}).get("schemas", {})
    for component_name, props in _iter_prop_containers(schemas):
        for prop_name, prop_schema in props.items():
            hashes = recorded.get((component_name, prop_name))
            # A property carrying several hashes (a oneOf of enums) cannot be
            # attributed to a single reference, so it is skipped here.
            if not hashes or len(hashes) != 1:
                continue
            ref_name = _resolve_enum_ref(prop_schema)
            if ref_name:
                name_hashes[ref_name].update(hashes)

    clashes = {name: hashes for name, hashes in name_hashes.items() if len(hashes) > 1}
    if clashes:
        lines = []
        for name, hashes in sorted(clashes.items()):
            value_sets = " vs ".join(str(hash_values.get(h, "?")) for h in sorted(hashes))
            lines.append(f'  "{name}": {value_sets}')
        raise RuntimeError(
            "One enum component name refers to two different choice sets, and the schema "
            "silently dropped one of them:\n"
            + "\n".join(lines)
            + "\nRename one of the Choices classes involved, or give one choice set its own "
            "name in ENUM_NAME_OVERRIDES (posthog/settings/web.py)."
        )
    return result


def _resolve_enum_ref(prop_schema: dict[str, Any]) -> str | None:
    """Return the enum component a post-processed property references."""
    schema = prop_schema
    if schema.get("type") == "array":
        schema = schema.get("items", {})
    nodes = [schema, *schema.get("allOf", []), *schema.get("oneOf", []), *schema.get("anyOf", [])]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = node.get("$ref", "").rsplit("/", 1)[-1]
        if name and name not in ("BlankEnum", "NullEnum"):
            return name
    return None
