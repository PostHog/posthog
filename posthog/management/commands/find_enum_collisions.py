"""Find drf-spectacular enum naming collisions and suggest ENUM_NAME_OVERRIDES entries.

Replicates the collision detection logic from drf_spectacular.hooks.postprocess_schema_enums
but prints actionable output instead of opaque warnings.

Run this when `hogli build:openapi-schema` fails with messages like
"enum naming encountered a non-optimally resolvable collision" / "Format5eaEnum" — it
prints a suggested ENUM_NAME_OVERRIDES entry for posthog/settings/web.py. The suggestion
is pastable as-is for type-hint enum collisions and for ChoiceField collisions whose
choices are plain inline lists (labels == values); only ChoiceField collisions with
custom labels (e.g. a `TextChoices` class where labels differ from values) need the
model class path filled in.

See also:
    posthog/settings/web.py — ENUM_NAME_OVERRIDES (where the fix goes)
    /improving-drf-endpoints — skill with the full DRF/OpenAPI guide

Usage:
    python manage.py find_enum_collisions
"""

from __future__ import annotations

import os
import re
import json
from collections import defaultdict
from collections.abc import MutableMapping
from typing import Any

from django.core.management.base import BaseCommand

from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.plumbing import list_hash, load_enum_name_overrides
from drf_spectacular.settings import spectacular_settings


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


class Command(BaseCommand):
    help = "Find drf-spectacular enum collisions and suggest ENUM_NAME_OVERRIDES entries"

    def handle(self, *args: object, **options: object) -> None:
        os.environ.setdefault("OPENAPI_INCLUDE_INTERNAL", "1")
        os.environ.setdefault("OPENAPI_MOCK_INTERNAL_API_SECRET", "1")

        GENERATOR_STATS.enable_trace_lineno()

        self.stderr.write("Generating schema (this takes ~30s)...")
        gen = SchemaGenerator()

        orig_hooks = list(spectacular_settings.POSTPROCESSING_HOOKS)
        spectacular_settings.POSTPROCESSING_HOOKS = []  # type: ignore[attr-defined]
        schema = gen.get_schema(request=None, public=True)
        spectacular_settings.POSTPROCESSING_HOOKS = orig_hooks  # type: ignore[attr-defined]

        schemas = schema.get("components", {}).get("schemas", {})
        overrides = load_enum_name_overrides()
        enum_suffix = spectacular_settings.ENUM_SUFFIX

        prop_hash_mapping: dict[str, set[str]] = defaultdict(set)
        hash_name_mapping: dict[str, set[tuple[str, str]]] = defaultdict(set)
        hash_values: dict[str, list] = {}
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

        collisions: list[dict] = []
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

        if not collisions:
            self.stdout.write(self.style.SUCCESS("No enum collisions found."))
            return

        self.stdout.write(f"\nFound {len(collisions)} enum collision(s):\n")

        for c in collisions:
            self.stdout.write(f"  Field: {c['field']}")
            self.stdout.write(f"  Auto-resolved as: {c['auto_name']}")
            self.stdout.write(f"  Hash: {c['hash']}")
            self.stdout.write(f"  Values: {c['values']}")
            path = "x-spec-enum-id (ChoiceField)" if c["has_spec_id"] else "inline (type-hint)"
            self.stdout.write(f"  Hash path: {path}")
            self.stdout.write(f"  Used in {len(c['components'])} components:")
            for comp, field in c["components"]:
                self.stdout.write(f"    - {comp}.{field}")

            self.stdout.write("")
            self.stdout.write("  Override entry to add to ENUM_NAME_OVERRIDES in web.py")
            self.stdout.write("  (key defaults to the current auto-resolved name; rename for a nicer schema type):")
            if c["has_spec_id"] and not c["inline_override_matches"]:
                self.stdout.write(f'    "{c["auto_name"]}": "your.models.module.Model.ChoicesClass",')
                self.stdout.write(
                    "    # ChoiceField with custom labels (labels != values) — override must be a model class path"
                )
            else:
                vals = c["values"]
                if all(isinstance(v, int) for v in vals):
                    formatted = [(v, v) for v in vals]
                    self.stdout.write(f'    "{c["auto_name"]}": {formatted},')
                else:
                    self.stdout.write(f'    "{c["auto_name"]}": {json.dumps(vals)},')
                if c["has_spec_id"]:
                    self.stdout.write(
                        "    # ChoiceField with inline choices (labels == values) — paste as-is to silence the warning"
                    )
                else:
                    self.stdout.write("    # Type-hint path — paste as-is to silence the warning")
            self.stdout.write("\n  ---\n")

        all_hashes = set()
        for hs in prop_hash_mapping.values():
            all_hashes.update(hs)

        stale = [(name, h) for h, name in overrides.items() if h not in all_hashes]
        if stale:
            self.stdout.write("Stale overrides (hash not found in schema, may be removable):")
            for name, h in sorted(stale):
                self.stdout.write(f"  {name} (hash: {h})")
            self.stdout.write("")
