#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to keep nested discriminated unions discriminated.

datamodel-code-generator collapses a discriminated union that is itself a member of another
discriminated union (`--collapse-root-models`), splicing the inner members into the outer union
and dropping the inner `discriminator`. Pydantic then sees several members with the same outer
discriminator value and refuses the model at import time.

This post-processor reads the source JSON schema, finds every discriminated union whose member is
another discriminated union on a different property, and rewrites each place in schema.py where the inner members appear
in sequence to `Annotated[<inner union>, Field(discriminator=<inner prop>)]`, which is the nested
form pydantic supports.

The rewrite matches the exact ordered member sequence extracted from the schema, so a sequence
that is not the inner union cannot match.
"""

from __future__ import annotations

import re
import json
from pathlib import Path

SCHEMA_JSON = Path("frontend/src/queries/schema.json")
SCHEMA_PY = Path("posthog/schema.py")


def _resolve_ref(definitions: dict, ref: str) -> dict:
    name = ref.removeprefix("#/definitions/")
    seen: set[str] = set()
    while name not in seen:
        seen.add(name)
        node = definitions.get(name, {})
        if list(node.keys()) == ["$ref"]:
            name = node["$ref"].removeprefix("#/definitions/")
            continue
        return node
    return {}


def _discriminated_members(node: dict) -> tuple[str, list[str]] | None:
    """Return (discriminator property, member names in oneOf order) for a discriminated union node."""
    discriminator = node.get("discriminator")
    one_of = node.get("oneOf")
    if not isinstance(discriminator, dict) or not isinstance(one_of, list) or len(one_of) < 2:
        return None
    prop = discriminator.get("propertyName")
    if not isinstance(prop, str):
        return None
    members: list[str] = []
    for variant in one_of:
        ref = variant.get("$ref") if isinstance(variant, dict) else None
        if not ref:
            return None
        members.append(ref.removeprefix("#/definitions/"))
    return prop, members


def _find_nested_unions(schema: dict) -> list[tuple[str, str]]:
    """Return (inner union text, inner discriminator) for every discriminated union nested in another."""
    definitions = schema.get("definitions", {})
    sites: dict[str, str] = {}
    for node in definitions.values():
        outer = _discriminated_members(node)
        if outer is None:
            continue
        for member in outer[1]:
            inner = _discriminated_members(_resolve_ref(definitions, f"#/definitions/{member}"))
            # Flattening is correct when both levels discriminate on the same property.
            if inner is None or inner[0] == outer[0]:
                continue
            sites[" | ".join(inner[1])] = inner[0]
    return sorted(sites.items())


def _patch_schema_py(sites: list[tuple[str, str]]) -> int:
    source = SCHEMA_PY.read_text()
    replacements = 0
    for union_text, prop in sites:
        members = union_text.split(" | ")
        sequence = r"\s*\|\s*".join(r"\b" + re.escape(member) + r"\b" for member in members)
        patched = f"Annotated[{union_text}, Field(discriminator={prop!r})]"
        source, n = re.subn(r"(?<!Annotated\[)" + sequence, patched, source)
        replacements += n
    if replacements and "Annotated" not in source.split("from pydantic")[0]:
        source = re.sub(
            r"^from typing import ([^\n]*)$",
            lambda m: f"from typing import Annotated, {m.group(1)}",
            source,
            count=1,
            flags=re.MULTILINE,
        )
    SCHEMA_PY.write_text(source)
    return replacements


def main() -> int:
    sites = _find_nested_unions(json.loads(SCHEMA_JSON.read_text()))
    if not sites:
        print("no nested discriminated unions found")
        return 0
    n = _patch_schema_py(sites)
    print(f"patched {n} nested discriminated union sites: {sites}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
