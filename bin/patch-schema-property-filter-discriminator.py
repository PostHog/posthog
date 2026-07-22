#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to discriminate the AnyPropertyFilter union.

The frontend AnyPropertyFilter union (22 members tagged by `type`) is inlined by
datamodel-code-generator at every usage site, so Pydantic validates it as a smart
union: a malformed filter produces one error per member and valid filters pay for
walking the variants. A JSON Schema `discriminator` keyword can't express this
union — it must keep accepting payloads a plain tag lookup rejects (missing
`type`, `{}` rows, multi-value log/span tags, the AND/OR-tagged recursive group) —
so this script rewrites each inlined union into a tagged union driven by the
callable discriminator in posthog/schema_discriminators.py.

Site discovery anchors on the exact member run in schema.json anyOf order. If the
union gains or loses a member, or a usage site is added or removed, the counts
below stop matching and this script fails the build on purpose: update MEMBER_TAGS
and EXPECTED_SITE_COUNTS together with the schema change, and extend
posthog/test/test_property_filter_discriminator.py accordingly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PY = Path("posthog/schema.py")

DISCRIMINATOR_MODULE = "posthog.schema_discriminators"
DISCRIMINATOR_FN = "property_filter_discriminator"
DISCRIMINATED_ALIAS = "AnyPropertyFilterDiscriminated"
DISCRIMINATED_GROUP_ALIAS = "AnyPropertyFilterOrGroupDiscriminated"

# AnyPropertyFilter members in schema.json anyOf order -> canonical discriminator tag.
# Non-canonical tag values (log_attribute, span_attribute, AND/OR, missing type) are
# folded onto these tags by the callable in posthog/schema_discriminators.py.
MEMBER_TAGS: dict[str, str] = {
    "EventPropertyFilter": "event",
    "PersonPropertyFilter": "person",
    "PersonMetadataPropertyFilter": "person_metadata",
    "ElementPropertyFilter": "element",
    "EventMetadataPropertyFilter": "event_metadata",
    "SessionPropertyFilter": "session",
    "CohortPropertyFilter": "cohort",
    "RecordingPropertyFilter": "recording",
    "LogEntryPropertyFilter": "log_entry",
    "GroupPropertyFilter": "group",
    "FeaturePropertyFilter": "feature",
    "FlagPropertyFilter": "flag",
    "HogQLPropertyFilter": "hogql",
    "EmptyPropertyFilter": "empty",
    "DataWarehousePropertyFilter": "data_warehouse",
    "DataWarehousePersonPropertyFilter": "data_warehouse_person_property",
    "ErrorTrackingIssueFilter": "error_tracking_issue",
    "LogPropertyFilter": "log",
    "MetricPropertyFilter": "metric_attribute",
    "SpanPropertyFilter": "span",
    "RevenueAnalyticsPropertyFilter": "revenue_analytics",
    "AccountCustomPropertyFilter": "account_custom_property",
    "WorkflowVariablePropertyFilter": "workflow_variable",
}

# How many union sites each rewrite must hit. A mismatch means the schema changed
# shape — fail the build so the change is made consciously (see module docstring).
EXPECTED_SITE_COUNTS = {
    # list[PropertyGroupFilter | PropertyGroupFilterValue | <members>]: the outer smart
    # union stays because PropertyGroupFilter and PropertyGroupFilterValue share the
    # AND/OR tag and cannot be discriminated apart.
    "group_prefixed": 3,
    # PropertyGroupFilterValue.values: list[PropertyGroupFilterValue | <members>] — the
    # recursive site, discriminated including the group via its AND/OR -> property_group tag.
    "recursive": 1,
    # Plain inlined runs: list[<members>], optionally `| PropertyGroupFilter` / `| None`.
    "plain": 61,
}


def _ensure_import_names(source: str, module: str, extra_names: list[str]) -> str:
    """Add names to a `from <module> import ...` statement (flat or parenthesized), keeping ASCII order.

    Emits the flat form; the trailing ruff format pass in build-schema-python.sh re-wraps it if needed.
    """
    import_re = re.compile(
        rf"^from {re.escape(module)} import (?:\((?P<paren>[^)]*)\)|(?P<flat>[^(\n]+))$", re.MULTILINE
    )
    match = import_re.search(source)
    if not match:
        raise ValueError(f"could not find `from {module} import ...` in {SCHEMA_PY}")
    raw_names = match.group("paren") or match.group("flat")
    names = [name.strip() for name in raw_names.split(",") if name.strip()]
    names.extend(name for name in extra_names if name not in names)
    names.sort()
    return source[: match.start()] + f"from {module} import " + ", ".join(names) + source[match.end() :]


def _alias_block() -> str:
    # `pydantic.Tag`/`pydantic.Discriminator` stay module-qualified: the generated schema
    # already contains an enum class named `Tag`, and bare names could collide with any
    # future generated symbol.
    tagged = [f'Annotated[{member}, pydantic.Tag("{tag}")]' for member, tag in MEMBER_TAGS.items()]
    union = "\n    | ".join(tagged)
    group_union = "\n    | ".join(['Annotated[PropertyGroupFilterValue, pydantic.Tag("property_group")]', *tagged])
    return (
        "# Added by bin/patch-schema-property-filter-discriminator.py: tagged AnyPropertyFilter\n"
        "# aliases so validation routes on `type` instead of trying every member. The callable\n"
        "# keeps legacy tolerance — see posthog/schema_discriminators.py.\n"
        f"{DISCRIMINATED_ALIAS} = Annotated[\n"
        f"    {union},\n"
        f"    pydantic.Discriminator({DISCRIMINATOR_FN}),\n"
        "]\n"
        "\n"
        f"{DISCRIMINATED_GROUP_ALIAS} = Annotated[\n"
        f"    {group_union},\n"
        f"    pydantic.Discriminator({DISCRIMINATOR_FN}),\n"
        "]\n"
    )


def main() -> int:
    source = SCHEMA_PY.read_text()

    if DISCRIMINATED_ALIAS in source:
        print("property-filter discriminator already applied — skipping")
        return 0

    member_run = r"\s*\|\s*".join(re.escape(member) for member in MEMBER_TAGS)
    group_prefixed_re = re.compile(r"PropertyGroupFilter\s*\|\s*PropertyGroupFilterValue\s*\|\s*" + member_run)
    recursive_re = re.compile(r"PropertyGroupFilterValue\s*\|\s*" + member_run)
    plain_re = re.compile(member_run)

    source, n_group = group_prefixed_re.subn(
        f"PropertyGroupFilter | PropertyGroupFilterValue | {DISCRIMINATED_ALIAS}", source
    )
    source, n_recursive = recursive_re.subn(DISCRIMINATED_GROUP_ALIAS, source)
    source, n_plain = plain_re.subn(DISCRIMINATED_ALIAS, source)

    found = {"group_prefixed": n_group, "recursive": n_recursive, "plain": n_plain}
    if found != EXPECTED_SITE_COUNTS:
        print(
            "error: property-filter union sites changed shape.\n"
            f"  expected {EXPECTED_SITE_COUNTS}\n"
            f"  found    {found}\n"
            "If you added/removed an AnyPropertyFilter member or usage site, update MEMBER_TAGS /\n"
            "EXPECTED_SITE_COUNTS in bin/patch-schema-property-filter-discriminator.py and extend\n"
            "posthog/test/test_property_filter_discriminator.py to cover the change.",
            file=sys.stderr,
        )
        return 1

    # The aliases must be defined before the trailing model_rebuild() calls so the
    # deferred annotations that reference them resolve.
    rebuild_match = re.search(r"^\w+\.model_rebuild\(\)$", source, re.MULTILINE)
    if not rebuild_match:
        print(f"error: could not find the model_rebuild() block in {SCHEMA_PY}", file=sys.stderr)
        return 1
    source = source[: rebuild_match.start()] + _alias_block() + "\n\n" + source[rebuild_match.start() :]

    source = _ensure_import_names(source, "typing", ["Annotated"])
    pydantic_import_re = re.compile(r"^from pydantic import ", re.MULTILINE)
    pydantic_match = pydantic_import_re.search(source)
    if not pydantic_match:
        print(f"error: could not find `from pydantic import ...` in {SCHEMA_PY}", file=sys.stderr)
        return 1
    source = (
        source[: pydantic_match.start()]
        + f"import pydantic\n\nfrom {DISCRIMINATOR_MODULE} import {DISCRIMINATOR_FN}\n\n"
        + source[pydantic_match.start() :]
    )

    SCHEMA_PY.write_text(source)
    print(f"patched {n_group + n_recursive + n_plain} property-filter union sites: {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
