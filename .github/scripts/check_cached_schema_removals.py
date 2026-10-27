#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Flag fields removed from the models that a cached query response stores.

PostHog stores each query response, with its modifiers, in the query cache.
The generated models reject unknown keys, so a cached entry that still holds a removed field
fails to parse and counts as a cache miss.
This script compares two copies of frontend/src/queries/schema.json and lists those removals.
It checks named definitions and the objects inline in them. Objects inside anyOf lists are not compared.

Usage:
    check_cached_schema_removals.py BASE_SCHEMA HEAD_SCHEMA COMMENT_FILE

Environment:
    PR_BODY        The pull request description. A line "Cache impact: <choice>" acknowledges a removal.
    GITHUB_OUTPUT  Optional. Receives "removed" and "acknowledged" as true or false.
"""

import os
import re
import sys
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKER = "<!-- cached-schema-removal -->"
ACKNOWLEDGEMENT = re.compile(r"^\s*Cache impact:\s*(deprecated|accepted|bumped)\b", re.IGNORECASE | re.MULTILINE)
CACHED_ROOT_PREFIX = "Cached"
DEFINITION_REF_PREFIX = "#/definitions/"

COMMENT_BODY = """\
{marker}
## This PR removes fields that cached query responses can still hold

PostHog stores each query response, with its modifiers, in the query cache.
The generated models reject unknown keys.
When PostHog reads a cached entry that holds a removed field, the entry fails to parse, counts as a cache miss, and sends one exception to error tracking.

**Removed from `frontend/src/queries/schema.json`:**

{removals}

**Choose one option.**
Add the matching line to the PR description. The check passes after the description changes.

| Option | Line to add | What happens | Cost |
| --- | --- | --- | --- |
| Keep the field as deprecated | `Cache impact: deprecated` | The field stays in the schema with `@deprecated`. A later PR removes it after the old entries expire (up to 7 days). | No cache misses. Needs a second PR. |
| Accept the misses | `Cache impact: accepted` | The field is removed now. | Each cached entry that holds the field is a miss until the query runs again or the entry expires (up to 7 days). A caller that calculates on a miss waits for ClickHouse. ClickHouse load and the exception rate go up, and the cache hit rate drops. Use this only when the field did not change query results. |
| Bump the cache version | `Cache impact: bumped` | Change `"version"` in `get_cache_payload` in `posthog/hogql_queries/query_runner.py`. | Every cached query result for every team is a miss, not only the entries that hold the field. Use this only when the field changed query results and old entries must not be served. |

{status}
"""


@dataclass(frozen=True)
class Removal:
    model: str
    location: str
    kind: str
    name: str

    def describe(self) -> str:
        where = f"`{self.model}`"
        if self.location:
            where += f" at `{self.location}`"
        return f"{where}: {self.kind} `{self.name}`"


def referenced_definitions(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(DEFINITION_REF_PREFIX):
            yield ref.removeprefix(DEFINITION_REF_PREFIX)
        for value in node.values():
            yield from referenced_definitions(value)
    elif isinstance(node, list):
        for item in node:
            yield from referenced_definitions(item)


def cached_definitions(definitions: dict[str, Any]) -> set[str]:
    pending = [name for name in definitions if name.startswith(CACHED_ROOT_PREFIX)]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        pending.extend(referenced_definitions(definitions[name]))
    return seen


def removed_fields(model: str, base: Any, head: Any, location: str) -> Iterator[Removal]:
    if not isinstance(base, dict) or not isinstance(head, dict):
        return
    for key, base_value in base.items():
        head_value = head.get(key)
        if key == "properties" and isinstance(base_value, dict):
            head_properties = head_value if isinstance(head_value, dict) else {}
            for name, base_property in base_value.items():
                child_location = f"{location}.{name}" if location else name
                if name not in head_properties:
                    yield Removal(model, location, "property", name)
                else:
                    yield from removed_fields(model, base_property, head_properties[name], child_location)
        elif key == "enum" and isinstance(base_value, list) and isinstance(head_value, list):
            for value in base_value:
                if value not in head_value:
                    yield Removal(model, location, "enum value", str(value))
        elif isinstance(base_value, dict):
            yield from removed_fields(model, base_value, head_value, location)


def find_removals(base_schema: dict[str, Any], head_schema: dict[str, Any]) -> list[Removal]:
    base_definitions = base_schema.get("definitions", {})
    head_definitions = head_schema.get("definitions", {})
    removals: list[Removal] = []
    for name in sorted(cached_definitions(base_definitions)):
        if name in head_definitions:
            removals.extend(removed_fields(name, base_definitions[name], head_definitions[name], ""))
    return removals


def find_acknowledgement(pr_body: str) -> str | None:
    match = ACKNOWLEDGEMENT.search(pr_body)
    return match.group(1).lower() if match else None


def render_comment(removals: list[Removal], acknowledgement: str | None) -> str:
    if acknowledgement:
        status = f"Acknowledged in the PR description: `Cache impact: {acknowledgement}`."
    else:
        status = "Not acknowledged yet. The check fails until the PR description has one of these lines."
    return COMMENT_BODY.format(
        marker=MARKER,
        removals="\n".join(f"- {removal.describe()}" for removal in removals),
        status=status,
    )


def main(argv: list[str]) -> int:
    base_path, head_path, comment_path = argv[1:4]
    removals = find_removals(json.loads(Path(base_path).read_text()), json.loads(Path(head_path).read_text()))
    acknowledgement = find_acknowledgement(os.environ.get("PR_BODY", ""))

    if removals:
        Path(comment_path).write_text(render_comment(removals, acknowledgement))
        for removal in removals:
            print(f"Removed: {removal.describe()}")
    else:
        print("No fields removed from cached response models.")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as output:
            output.write(f"removed={str(bool(removals)).lower()}\n")
            output.write(f"acknowledged={str(acknowledgement is not None).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
