#!/usr/bin/env python3
"""
Restore Pydantic v2 discriminator annotations in posthog/schema.py after
datamodel-codegen.

The pinned datamodel-code-generator drops JSON-Schema `discriminator`
annotations on inline list-item unions when `--collapse-root-models` is
enabled. For any field whose value type is a `list[A | B | ...]` union of
classes that share a `kind` literal, the annotation is re-applied here as
`Annotated[..., Field(discriminator="kind")]`. Without this, Pydantic walks
every variant on a bad value and produces one error per branch instead of
a single targeted error.

Idempotent: lines already wrapped with `Field(discriminator="kind")` are
left untouched.
"""

# ruff: noqa: T201 allow print statements

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PATH = Path("posthog/schema.py")

# Field names whose value type is expected to be a discriminated union of
# `kind`-bearing classes. Add new field names here when codegen drops the
# discriminator on another `list[A | B | ...]` field.
DISCRIMINATED_LIST_FIELDS = ("series", "nodes")

# Match `<field>: list[<UnionMember>(?: | <UnionMember>)+]<rest>` where each
# member is heuristically an EntityNode-like class (name ends in "Node") and
# the union has at least two members.
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
        print("restore-schema-discriminators: no discriminated list unions to patch")
        return
    SCHEMA_PATH.write_text(patched)
    print(f"restore-schema-discriminators: restored {count} discriminator annotation(s)")


if __name__ == "__main__":
    main()
