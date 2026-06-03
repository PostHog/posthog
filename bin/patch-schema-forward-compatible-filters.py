#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to keep selected query filters forward-compatible."""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PY = Path("posthog/schema.py")
FORWARD_COMPATIBLE_FILTERS = ("AssistantTrendsFilter", "TrendsFilter")


def _patch_filter_extra_handling(source: str, class_name: str) -> tuple[str, int]:
    class_re = re.compile(
        r"(?P<prefix>class "
        + re.escape(class_name)
        + r"\(BaseModel\):\n"
        + r"    model_config = ConfigDict\(\n"
        + r"        extra=\")forbid(?P<suffix>\",\n"
        + r"    \)\n)"
    )

    source, replacements = class_re.subn(r"\g<prefix>ignore\g<suffix>", source, count=1)
    if replacements:
        return source, replacements

    already_patched_re = re.compile(
        r"class "
        + re.escape(class_name)
        + r"\(BaseModel\):\n"
        + r"    model_config = ConfigDict\(\n"
        + r"        extra=\"ignore\",\n"
        + r"    \)\n"
    )
    if already_patched_re.search(source):
        return source, 0

    print(f"warning: no forward-compatible filter patch site matched for {class_name}", file=sys.stderr)
    return source, 0


def main() -> int:
    source = SCHEMA_PY.read_text()
    total_replacements = 0

    for class_name in FORWARD_COMPATIBLE_FILTERS:
        source, replacements = _patch_filter_extra_handling(source, class_name)
        total_replacements += replacements

    if total_replacements:
        SCHEMA_PY.write_text(source)

    print(f"patched {total_replacements} forward-compatible filter model configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
