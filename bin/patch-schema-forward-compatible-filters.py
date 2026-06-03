#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to keep selected query filters forward-compatible."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PY = Path("posthog/schema.py")
FORWARD_COMPATIBLE_FILTERS = ("AssistantTrendsFilter", "TrendsFilter")


def _patch_filter_extra_handling(source: str, class_name: str) -> tuple[str, int, bool]:
    class_re = re.compile(
        r"(?P<prefix>class "
        + re.escape(class_name)
        + r"\(BaseModel\):\n"
        + r"    model_config = ConfigDict\(\n"
        + r"        extra=)(?P<quote>[\"'])forbid(?P=quote)(?P<suffix>,\n"
        + r"    \)\n)"
    )

    def replace(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{match.group('prefix')}{quote}ignore{quote}{match.group('suffix')}"

    source, replacements = class_re.subn(replace, source, count=1)
    if replacements:
        return source, replacements, True

    already_patched_re = re.compile(
        r"class "
        + re.escape(class_name)
        + r"\(BaseModel\):\n"
        + r"    model_config = ConfigDict\(\n"
        + r"        extra=[\"']ignore[\"'],\n"
        + r"    \)\n"
    )
    if already_patched_re.search(source):
        return source, 0, True

    return source, 0, False


def main() -> int:
    source = SCHEMA_PY.read_text()
    total_replacements = 0
    failed_class_names: list[str] = []

    for class_name in FORWARD_COMPATIBLE_FILTERS:
        source, replacements, matched = _patch_filter_extra_handling(source, class_name)
        total_replacements += replacements
        if not matched:
            failed_class_names.append(class_name)

    if failed_class_names:
        print(
            "failed to patch forward-compatible filter model configs: " + ", ".join(failed_class_names),
            file=sys.stderr,
        )
        return 1

    if total_replacements:
        SCHEMA_PY.write_text(source)

    print(f"patched {total_replacements} forward-compatible filter model configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
