#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to apply array-element discriminators.

datamodel-code-generator 0.36 propagates JSON Schema `discriminator` keywords
onto direct field types, but drops them when the discriminated union is inside
an array (the `items: {$ref: <discriminated_union>}` pattern). Upstream tracking:
the metadata never reaches the generated `list[...]` annotation, so Pydantic
walks every variant and emits errors for each, leaving LLM clients with
multi-variant noise.

This post-processor reads the source JSON schema, finds every list whose items
$ref resolves to a discriminated union, and rewrites the matching field in
schema.py to use `list[Annotated[<union>, Field(discriminator=<prop>)]]`.

Limit it to the exact (class, field, union_text) tuples extracted from the
schema — never a global regex against schema.py — so an accidental match
elsewhere can't silently mutate unrelated fields.
"""

from __future__ import annotations

import re
import sys
import json
from pathlib import Path

SCHEMA_JSON = Path("frontend/src/queries/schema.json")
SCHEMA_PY = Path("posthog/schema.py")


def _resolve_ref(definitions: dict, ref: str) -> dict:
    """Walk a `#/definitions/Foo` ref, hopping through alias `$ref`s."""
    name = ref.removeprefix("#/definitions/")
    seen: set[str] = set()
    while name not in seen:
        seen.add(name)
        node = definitions.get(name, {})
        # Single $ref aliases (e.g. ExperimentFunnelMetricStep -> *Union).
        if list(node.keys()) == ["$ref"]:
            name = node["$ref"].removeprefix("#/definitions/")
            continue
        return node
    return {}


def _union_members_python(definitions: dict, union_node: dict) -> list[str] | None:
    """Return the Python union member names in oneOf order, or None if not applicable."""
    one_of = union_node.get("oneOf")
    if not isinstance(one_of, list) or len(one_of) < 2:
        return None
    members: list[str] = []
    for variant in one_of:
        ref = variant.get("$ref") if isinstance(variant, dict) else None
        if not ref:
            return None
        members.append(ref.removeprefix("#/definitions/"))
    return members


def _find_array_discriminator_sites(schema: dict) -> list[tuple[str, str, str, str]]:
    """Return (class_name, field_name, union_text, discriminator_prop) tuples to patch."""
    definitions = schema.get("definitions", {})
    sites: list[tuple[str, str, str, str]] = []

    for class_name, class_node in definitions.items():
        properties = class_node.get("properties")
        if not isinstance(properties, dict):
            continue
        for field_name, field_node in properties.items():
            if not isinstance(field_node, dict):
                continue
            if field_node.get("type") != "array":
                continue
            items = field_node.get("items")
            if not isinstance(items, dict):
                continue
            ref = items.get("$ref")
            if not ref:
                continue
            target = _resolve_ref(definitions, ref)
            discriminator = target.get("discriminator")
            if not isinstance(discriminator, dict):
                continue
            prop = discriminator.get("propertyName")
            if not isinstance(prop, str):
                continue
            members = _union_members_python(definitions, target)
            if not members:
                continue
            union_text = " | ".join(members)
            sites.append((class_name, field_name, union_text, prop))
    return sites


def _patch_schema_py(sites: list[tuple[str, str, str, str]]) -> int:
    source = SCHEMA_PY.read_text()
    replacements = 0

    for class_name, field_name, union_text, prop in sites:
        # Match the class body and within it the single line declaring the field as a list
        # of the inlined union. `re.DOTALL` lets `.*?` span newlines until the field line.
        class_re = re.compile(
            r"(class "
            + re.escape(class_name)
            + r"\b[^\n]*:\n.*?\n    "
            + re.escape(field_name)
            + r": )list\["
            + re.escape(union_text)
            + r"\](?P<tail>[^\n]*)\n",
            re.DOTALL,
        )

        def _replace(m: re.Match[str], union_text: str = union_text, prop: str = prop) -> str:
            inner = f"Annotated[{union_text}, Field(discriminator={prop!r})]"
            return f"{m.group(1)}list[{inner}]{m.group('tail')}\n"

        source, n = class_re.subn(_replace, source, count=1)
        if n == 0:
            # Either the field is already patched (idempotent re-run) or it genuinely
            # isn't where we expect. Distinguish by looking for the already-patched form.
            already_patched_re = re.compile(
                r"class "
                + re.escape(class_name)
                + r"\b[^\n]*:\n.*?\n    "
                + re.escape(field_name)
                + r": list\[Annotated\["
                + re.escape(union_text)
                + r", Field\(discriminator=",
                re.DOTALL,
            )
            if not already_patched_re.search(source):
                print(
                    f"warning: no array-discriminator patch site matched for "
                    f"{class_name}.{field_name} (union={union_text!r}) — skipping",
                    file=sys.stderr,
                )
            continue
        replacements += n

    if replacements == 0:
        return 0

    # Ensure `Annotated` is imported from typing.
    if "Annotated" not in source.split("from pydantic")[0]:
        source = re.sub(
            r"^from typing import ([^\n]*)$",
            lambda m: f"from typing import Annotated, {m.group(1)}" if "Annotated" not in m.group(1) else m.group(0),
            source,
            count=1,
            flags=re.MULTILINE,
        )

    SCHEMA_PY.write_text(source)
    return replacements


def main() -> int:
    schema = json.loads(SCHEMA_JSON.read_text())
    sites = _find_array_discriminator_sites(schema)
    if not sites:
        print("no array-discriminator sites found")
        return 0
    n = _patch_schema_py(sites)
    print(f"patched {n} array-discriminator sites: {sites}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
