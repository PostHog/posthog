#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements in this build script

"""Post-process posthog/schema.py to make selected filter models forward-compatible.

`additionalProperties: false` on the frontend schema interfaces becomes
`extra="forbid"` on the generated Pydantic models. That is the right default for
freshly-submitted API input, but it is hostile to query JSON that is *persisted*
and *replayed* later — saved insights, CSV/subscription exports, and the
persons-modal actor drilldown all re-validate stored `trendsFilter` payloads.

Two ways that bites us:

- During a rolling deploy a newer client persists an additive field (e.g. a new
  axis-label key) that older in-flight workers do not yet know about, so their
  stale `extra="forbid"` model rejects the whole query before any rows compute.
- A leaked visualization-only key reaches a stored `trendsFilter` and then
  permanently fails every future re-validation.

Relaxing these specific models to `extra="ignore"` keeps strict frontend types
while letting persisted/replayed payloads survive additive or leaked keys —
unknown keys are dropped on validation instead of raising.

Limit the rewrite to an explicit allowlist of (class) names — never a global
regex against schema.py — so an accidental match elsewhere can't silently
loosen unrelated models.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCHEMA_PY = Path("posthog/schema.py")

# Models that validate persisted/replayed query JSON and must tolerate additive
# or leaked keys. Keep this list tight and justified — every entry loosens
# validation for that model everywhere it is used.
FORWARD_COMPATIBLE_FILTER_CLASSES = (
    "TrendsFilter",
    "AssistantTrendsFilter",
)


def _patch_schema_py(class_names: tuple[str, ...]) -> int:
    source = SCHEMA_PY.read_text()
    replacements = 0

    for name in class_names:
        # Anchor on the class header and its model_config, which the generator
        # always emits as the first statement in the class body. `\s*` spans the
        # newline+indent of the multi-line `ConfigDict(\n    extra="forbid",\n)`
        # form as well as a collapsed single-line form.
        forbid_re = re.compile(
            r'(class ' + re.escape(name) + r'\(BaseModel\):\n    model_config = ConfigDict\(\s*extra=")forbid(")'
        )
        source, n = forbid_re.subn(r"\1ignore\2", source, count=1)
        if n == 0:
            already_ignore_re = re.compile(
                r"class " + re.escape(name) + r'\(BaseModel\):\n    model_config = ConfigDict\(\s*extra="ignore"'
            )
            if not already_ignore_re.search(source):
                print(
                    f"warning: no extra=\"forbid\" patch site matched for {name} — "
                    f"the class may have been renamed or its config changed; skipping",
                    file=sys.stderr,
                )
            continue
        replacements += n

    if replacements:
        SCHEMA_PY.write_text(source)
    return replacements


def main() -> int:
    n = _patch_schema_py(FORWARD_COMPATIBLE_FILTER_CLASSES)
    print(f"patched {n} forward-compatible filter models: {FORWARD_COMPATIBLE_FILTER_CLASSES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
