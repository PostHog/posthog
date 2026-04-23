#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
CI script to verify dorny/paths-filter negation patterns are guarded.

With dorny's default predicate-quantifier ('some'), each filter rule is OR'd
independently. A '!path' rule then matches every file NOT at that path — which
silently inverts the intended exclusion. Using '!' patterns is only safe when
the step also sets `predicate-quantifier: 'every'`.

Docs: https://github.com/dorny/paths-filter#advanced-options

Usage:
    uv run .github/scripts/check-dorny-paths-filter.py
"""

import sys
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
DORNY_PREFIX = "dorny/paths-filter@"
DOCS_URL = "https://github.com/dorny/paths-filter#advanced-options"


def parse_filters(raw: Any) -> dict[str, list[str]] | None:
    """Return the filter dict, or None if it's an unparseable external path ref."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    # dorny also accepts a path to an external filters file; those are
    # single-line strings without the block scalar's newline structure.
    if "\n" not in raw and ":" not in raw:
        return None
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def negation_patterns(filters: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Return (filter_name, pattern) pairs for every '!' pattern found."""
    hits: list[tuple[str, str]] = []
    for name, patterns in filters.items():
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if isinstance(pattern, str) and pattern.startswith("!"):
                hits.append((name, pattern))
    return hits


def check_workflows() -> tuple[list[str], int, int]:
    errors: list[str] = []
    workflow_count = 0
    step_count = 0

    for workflow_file in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        workflow_count += 1
        with open(workflow_file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                errors.append(f"{workflow_file.name}: failed to parse YAML: {e}")
                continue

        if not isinstance(data, dict):
            continue

        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            continue

        for job_name, job_config in jobs.items():
            if not isinstance(job_config, dict):
                continue
            steps = job_config.get("steps")
            if not isinstance(steps, list):
                continue

            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith(DORNY_PREFIX):
                    continue

                step_count += 1
                with_block = step.get("with")
                if not isinstance(with_block, dict):
                    continue

                filters = parse_filters(with_block.get("filters"))
                if filters is None:
                    continue

                negations = negation_patterns(filters)
                if not negations:
                    continue

                quantifier = with_block.get("predicate-quantifier")
                if quantifier == "every":
                    continue

                step_ref = f"step id '{step['id']}'" if step.get("id") else f"step[{idx}]"
                filter_name, pattern = negations[0]
                errors.append(
                    f"{workflow_file.name}: job '{job_name}' ({step_ref}): "
                    f"filter '{filter_name}' uses negation '{pattern}' without "
                    f"`predicate-quantifier: 'every'` — with the default "
                    f"'some' quantifier, '!' rules match every file NOT at the "
                    f"path (including unrelated changes). See {DOCS_URL}."
                )

    return errors, workflow_count, step_count


def main() -> None:
    errors, workflow_count, step_count = check_workflows()
    if errors:
        print(f"Found {len(errors)} unsafe dorny/paths-filter negation(s):\n")
        for error in errors:
            print(f"  - {error}")
        print(
            "\nFix: either remove the '!' patterns and use positive filters "
            "with count comparison, or add `predicate-quantifier: 'every'` "
            f"to the step's `with:` block. See {DOCS_URL}."
        )
        sys.exit(1)

    print(
        f"Checked {workflow_count} workflow(s); {step_count} dorny/paths-filter "
        f"step(s); all negation usages guarded by predicate-quantifier: 'every'."
    )


if __name__ == "__main__":
    main()
