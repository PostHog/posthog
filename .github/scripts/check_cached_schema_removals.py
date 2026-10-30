#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Flag fields removed from the models that a cached query response stores.

PostHog stores each query response, with its modifiers, in the query cache.
The generated models reject unknown keys, so a cached entry that still holds a removed field
fails to parse and counts as a cache miss.
This script compares two copies of frontend/src/queries/schema.json and lists those removals.
It checks named definitions and the objects inline in them, and follows a $ref when only one side has it.
It looks through a nullable wrapper (an anyOf of one type and null) and skips every other anyOf or oneOf union.

Usage:
    check_cached_schema_removals.py BASE_SCHEMA HEAD_SCHEMA

Environment:
    PR_LABELS      The pull request labels, one per line. A cache-impact label acknowledges a removal.
    GITHUB_OUTPUT  Optional. Receives "removed", "acknowledged", "status", "summary" and "body".
                   The last three describe the CI report section. Without it, the script prints them.
"""

import os
import sys
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ACKNOWLEDGEMENT_LABELS = {
    "cache-impact-deprecated": "deprecated",
    "cache-impact-accepted": "accepted",
    "cache-impact-bumped": "bumped",
}
CACHED_ROOT_PREFIX = "Cached"
DEFINITION_REF_PREFIX = "#/definitions/"
NULL_BRANCH = {"type": "null"}

SECTION_BODY = """\
PostHog stores each query response, with its modifiers, in the query cache.
The generated models reject unknown keys.
When PostHog reads a cached entry that holds a removed field, the entry fails to parse, counts as a cache miss, and sends one exception to error tracking.

**Removed from `frontend/src/queries/schema.json`:**

{removals}

**Choose one option.**
Apply the matching label to the PR, then re-run the failed `Frontend typechecking` job. A label does not start CI by itself.

| Option | Label | What happens | Cost |
| --- | --- | --- | --- |
| Keep the field as deprecated | `cache-impact-deprecated` | The field stays in the schema with `@deprecated`, and the code stops writing it to cached responses. A later PR removes it after the entries written before that expire (up to 7 days). | No cache misses, if nothing writes the field during the wait. Needs a second PR. |
| Accept the misses | `cache-impact-accepted` | The field is removed now. | Each cached entry that holds the field is a miss until the query runs again or the entry expires (up to 7 days). A caller that calculates on a miss waits for ClickHouse. ClickHouse load and the exception rate go up, and the cache hit rate drops. Use this only when the field did not change query results. |
| Bump the cache version | `cache-impact-bumped` | Change `"version"` in `get_cache_payload` in `posthog/hogql_queries/query_runner.py`. | Every cached query result for every team is a miss, not only the entries that hold the field. Use this only when the field changed query results and old entries must not be served. |

Not sure which option fits your change? Ask in [this Slack channel](https://posthog.slack.com/archives/C076E99B152). The team is happy to help.

{status}
"""


@dataclass(frozen=True, kw_only=True, slots=True)
class Removal:
    model: str
    location: str
    kind: Literal["property", "enum value"]
    name: str

    def describe(self) -> str:
        where = f"`{self.model}`"
        if self.location:
            where += f" at `{self.location}`"
        return f"{where}: {self.kind} `{self.name}`"


def reference_name(node: Any) -> str | None:
    ref = node.get("$ref") if isinstance(node, dict) else None
    if isinstance(ref, str) and ref.startswith(DEFINITION_REF_PREFIX):
        return ref.removeprefix(DEFINITION_REF_PREFIX)
    return None


def referenced_definitions(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        ref = reference_name(node)
        if ref is not None:
            yield ref
        for value in node.values():
            yield from referenced_definitions(value)
    elif isinstance(node, list):
        for item in node:
            yield from referenced_definitions(item)


def allowed_values(node: dict[str, Any]) -> list[Any] | None:
    if isinstance(node.get("enum"), list):
        return node["enum"]
    if "const" in node:
        return [node["const"]]
    return None


def without_null(node: Any) -> Any:
    branches = node.get("anyOf") if isinstance(node, dict) else None
    if isinstance(branches, list) and NULL_BRANCH in branches:
        others = [branch for branch in branches if branch != NULL_BRANCH]
        if len(others) == 1:
            return others[0]
    return node


def is_union(node: dict[str, Any]) -> bool:
    return isinstance(node.get("anyOf"), list) or isinstance(node.get("oneOf"), list)


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


@dataclass(frozen=True, kw_only=True, slots=True)
class RefPair:
    base: str
    head: str


@dataclass(frozen=True, kw_only=True, slots=True)
class SchemaPair:
    base_definitions: dict[str, Any]
    head_definitions: dict[str, Any]
    compared: set[RefPair] = field(default_factory=set)

    def removed_fields(self, model: str, base: Any, head: Any, location: str) -> Iterator[Removal]:
        base = without_null(base)
        head = without_null(head)
        base_ref = reference_name(base)
        head_ref = reference_name(head)
        if base_ref is not None and base_ref == head_ref:
            return
        if base_ref is not None and head_ref is not None:
            ref_pair = RefPair(base=base_ref, head=head_ref)
            if ref_pair in self.compared:
                return
            self.compared.add(ref_pair)
        if base_ref is not None or head_ref is not None:
            base = self.base_definitions.get(base_ref) if base_ref is not None else base
            head = self.head_definitions.get(head_ref) if head_ref is not None else head
        if not isinstance(base, dict) or not isinstance(head, dict):
            return
        if is_union(base) or is_union(head):
            return
        base_values = allowed_values(base)
        head_values = allowed_values(head)
        if base_values is not None and head_values is not None:
            for value in base_values:
                if value not in head_values:
                    yield Removal(model=model, location=location, kind="enum value", name=str(value))
        for key, base_value in base.items():
            head_value = head.get(key)
            if key == "properties" and isinstance(base_value, dict):
                head_properties = head_value if isinstance(head_value, dict) else {}
                for name, base_property in base_value.items():
                    child_location = f"{location}.{name}" if location else name
                    if name not in head_properties:
                        yield Removal(model=model, location=location, kind="property", name=name)
                    else:
                        yield from self.removed_fields(model, base_property, head_properties[name], child_location)
            elif isinstance(base_value, dict):
                yield from self.removed_fields(model, base_value, head_value, location)


def find_removals(base_schema: dict[str, Any], head_schema: dict[str, Any]) -> list[Removal]:
    pair = SchemaPair(
        base_definitions=base_schema.get("definitions", {}), head_definitions=head_schema.get("definitions", {})
    )
    removals: list[Removal] = []
    for name in sorted(cached_definitions(pair.base_definitions)):
        if name in pair.head_definitions:
            removals.extend(pair.removed_fields(name, pair.base_definitions[name], pair.head_definitions[name], ""))
    return removals


def find_acknowledgement(labels: list[str]) -> str | None:
    for label, choice in ACKNOWLEDGEMENT_LABELS.items():
        if label in labels:
            return choice
    return None


@dataclass(frozen=True, kw_only=True, slots=True)
class Section:
    status: Literal["warn", "alert"]
    summary: str
    body: str


def render_body(removals: list[Removal], status: str) -> str:
    return SECTION_BODY.format(removals="\n".join(f"- {removal.describe()}" for removal in removals), status=status)


def render_section(removals: list[Removal], acknowledgement: str | None) -> Section:
    count = f"{len(removals)} removed field{'' if len(removals) == 1 else 's'}"
    if acknowledgement:
        status = f"Acknowledged with the `cache-impact-{acknowledgement}` label."
        return Section(
            status="warn",
            summary=f"{count}, acknowledged ({acknowledgement})",
            body=render_body(removals, status),
        )
    status = "Not acknowledged yet. `Frontend typechecking` fails until the PR has one of these labels."
    return Section(status="alert", summary=f"{count}, not acknowledged", body=render_body(removals, status))


def write_outputs(removals: list[Removal], acknowledgement: str | None, section: Section | None) -> None:
    fields = {
        "removed": str(bool(removals)).lower(),
        "acknowledged": str(acknowledgement is not None).lower(),
        "status": section.status if section else "ok",
        "summary": section.summary if section else "no removed fields",
    }
    lines = [f"{name}={value}\n" for name, value in fields.items()]
    if section:
        delimiter = f"EOF-{uuid.uuid4()}"
        lines.append(f"body<<{delimiter}\n{section.body}\n{delimiter}\n")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a") as output:
            output.writelines(lines)
    else:
        print("".join(lines), end="")


def main(argv: list[str]) -> int:
    base_path, head_path = argv[1:3]
    removals = find_removals(json.loads(Path(base_path).read_text()), json.loads(Path(head_path).read_text()))
    acknowledgement = find_acknowledgement(os.environ.get("PR_LABELS", "").splitlines())
    section = render_section(removals, acknowledgement) if removals else None

    for removal in removals:
        print(f"Removed: {removal.describe()}")
    if not removals:
        print("No fields removed from cached response models.")
    write_outputs(removals, acknowledgement, section)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
