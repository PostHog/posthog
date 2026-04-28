#!/usr/bin/env python3
"""
Post-process posthog/schema.py after datamodel-codegen.

Adds Pydantic v2 `Annotated[..., Field(discriminator="kind")]` wrappers around
the entity-node unions used as `series` (TrendsQuery / FunnelsQuery / etc.)
and as `nodes` (GroupNode). The pinned datamodel-code-generator version does
not propagate JSON-Schema `discriminator` annotations through inline list-item
unions when `--collapse-root-models` is enabled, so without this step Pydantic
walks every variant and stacks one error per branch (the original cause of
the 46-error TrendsQuery validation failures observed in production).

The transformation is idempotent: if the field is already wrapped with
`Annotated[..., Field(discriminator="kind")]`, the line is left untouched.
"""

# ruff: noqa: T201 allow print statements

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PATH = Path("posthog/schema.py")

# Field names whose value type is a union of entity nodes that all share
# `kind: Literal[...]`. We wrap these with Pydantic's discriminator so a bad
# entry produces a single targeted error rather than one error per variant.
DISCRIMINATED_LIST_FIELDS = ("series", "nodes")

# Capture: list[ <union> ] = Field(...) or list[ <union> ]\n
# We only target unions of EntityNode-like classes (heuristic: each member ends
# in "Node" and the union contains 2+ members joined by " | ").
LIST_FIELD_RE = re.compile(
    r"^(?P<indent>\s*)(?P<name>" + "|".join(DISCRIMINATED_LIST_FIELDS) + r")"
    r": list\[(?P<union>[A-Za-z_][A-Za-z0-9_]*Node(?: \| [A-Za-z_][A-Za-z0-9_]*Node)+)\]"
    r"(?P<rest>.*)$",
    re.MULTILINE,
)


TYPING_IMPORT_RE = re.compile(r"^(from typing import )(.+)$", re.MULTILINE)


def ensure_annotated_import(source: str) -> str:
    match = TYPING_IMPORT_RE.search(source)
    if not match:
        raise SystemExit("posthog/schema.py is missing `from typing import ...`; refusing to patch")

    names = [n.strip() for n in match.group(2).split(",")]
    if "Annotated" in names:
        return source
    names.append("Annotated")
    names.sort()
    new_import = match.group(1) + ", ".join(names)
    return source[: match.start()] + new_import + source[match.end() :]


def patch(source: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        union = match["union"]
        rest = match["rest"]
        # Skip if already wrapped with Annotated[..., discriminator=...]
        if 'discriminator="kind"' in match.group(0):
            return match.group(0)
        count += 1
        return (
            f"{match['indent']}{match['name']}: list[\n"
            f'{match["indent"]}    Annotated[{union}, Field(discriminator="kind")]\n'
            f"{match['indent']}]{rest}"
        )

    patched = LIST_FIELD_RE.sub(replace, source)
    if count > 0:
        patched = ensure_annotated_import(patched)
    return patched, count


def main() -> None:
    if not SCHEMA_PATH.exists():
        sys.exit(f"{SCHEMA_PATH} does not exist; run datamodel-codegen first")
    source = SCHEMA_PATH.read_text()
    patched, count = patch(source)
    if count == 0:
        print("postprocess-schema-python: no series/nodes unions to discriminate")
        return
    SCHEMA_PATH.write_text(patched)
    print(f"postprocess-schema-python: discriminated {count} entity-node union(s)")


if __name__ == "__main__":
    main()
