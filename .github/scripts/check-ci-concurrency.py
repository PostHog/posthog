#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
CI script to verify GitHub Actions workflow concurrency is configured correctly.

Two checks:

1. PR-triggered workflows must declare a top-level `concurrency:` block — without it,
   every push to a PR branch starts a fresh run while the in-flight one keeps burning
   minutes.

2. The concurrency group must not fall back to `github.run_id` — `github.head_ref` is
   empty on `push` events, so `head_ref || run_id` makes every push run land in its own
   unique group, silently disabling dedup. Use `github.ref` as the fallback instead.
   See PR #53194 (the agent-skills release race) for the failure mode.

Repo convention:

    concurrency:
        group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}
        cancel-in-progress: ${{ github.event_name == 'pull_request' }}

Usage:
    uv run .github/scripts/check-ci-concurrency.py
"""

import re
import sys
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

BAD_FALLBACK = re.compile(r"head_ref\s*\|\|\s*github\.run_id")

# Workflows intentionally exempt from concurrency cancellation.
# Each entry has a one-line reason so the next reader knows why.
SKIP = {
    # Telemetry / shadow measurement — cancelling stale runs may drop data.
    "ci-test-selection-shadow.yml",
    # Schedule-dominant; PR trigger filtered to a single script — cosmetic gain.
    "ci-backend-update-test-timing.yml",
    # Migration enforcement; arguably wants to complete on every PR state.
    "ci-migrations-service-separation-check.yml",
}

PR_TRIGGERS = {"pull_request", "pull_request_target"}


def is_pr_triggered(triggers: object) -> bool:
    if isinstance(triggers, str):
        return triggers in PR_TRIGGERS
    if isinstance(triggers, list):
        return any(t in PR_TRIGGERS for t in triggers)
    if isinstance(triggers, dict):
        return any(t in PR_TRIGGERS for t in triggers)
    return False


def check_concurrency() -> tuple[list[str], list[str], list[str]]:
    parse_errors: list[str] = []
    missing: list[str] = []
    bad_group: list[str] = []
    for workflow_file in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        with open(workflow_file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                parse_errors.append(f"{workflow_file.name}: failed to parse YAML: {e}")
                continue

        if not isinstance(data, dict):
            continue

        concurrency = data.get("concurrency")
        # Concurrency can be either a string (group only) or a mapping (group + cancel-in-progress).
        group_expr = ""
        if isinstance(concurrency, dict):
            group_expr = concurrency.get("group") or ""
        elif isinstance(concurrency, str):
            group_expr = concurrency
        if isinstance(group_expr, str) and BAD_FALLBACK.search(group_expr):
            bad_group.append(workflow_file.name)

        # PyYAML parses the top-level `on:` key as boolean True.
        triggers = data.get(True, data.get("on"))
        if not is_pr_triggered(triggers):
            continue
        if workflow_file.name.startswith("ci-") and workflow_file.name not in SKIP and concurrency is None:
            missing.append(f"{workflow_file.name}: missing top-level concurrency block")

    return parse_errors, missing, bad_group


def main() -> None:
    parse_errors, missing, bad_group = check_concurrency()
    failed = False

    if parse_errors:
        failed = True
        print(f"Found {len(parse_errors)} workflow file(s) with YAML parse errors:\n")
        for error in parse_errors:
            print(f"  - {error}")
        print()

    if bad_group:
        failed = True
        print(f"Found {len(bad_group)} workflow(s) with broken concurrency group fallback:\n")
        for name in bad_group:
            print(f"  - {name}")
        print(
            "\n`github.head_ref` is empty on push events — the `|| github.run_id` fallback gives every push run its\n"
            "own unique group, silently disabling dedup. Use `github.ref` as the fallback instead:\n"
        )
        print("    group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}")
        print("\nSee PR #53194 (agent-skills release race) for the failure mode.\n")

    if missing:
        failed = True
        print(f"Found {len(missing)} PR-triggered workflow(s) missing concurrency:\n")
        for error in missing:
            print(f"  - {error}")
        print("\nFix by adding this block after `on:`:\n")
        print("concurrency:")
        print("    group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}")
        print("    cancel-in-progress: ${{ github.event_name == 'pull_request' }}")
        print("\nOr, if cancelling stale runs would lose data (telemetry, schedule-only PR triggers, etc.),")
        print(f"add the filename to the SKIP set in {Path(__file__).name} with a one-line reason.")

    if failed:
        sys.exit(1)
    print("All workflow concurrency configurations look good.")


if __name__ == "__main__":
    main()
