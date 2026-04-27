#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
CI script to verify PR-triggered GitHub Actions workflows declare top-level concurrency.

Without `concurrency:`, every push to a PR branch starts a fresh run while the
in-flight one keeps burning minutes. The repo convention (used by 30+ workflows)
is:

    concurrency:
        group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
        cancel-in-progress: ${{ github.event_name == 'pull_request' }}

Usage:
    uv run .github/scripts/check-ci-concurrency.py
"""

import sys
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"

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


def check_concurrency() -> list[str]:
    errors: list[str] = []
    for workflow_file in sorted(WORKFLOWS_DIR.glob("ci-*.y*ml")):
        if workflow_file.name in SKIP:
            continue

        with open(workflow_file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                errors.append(f"{workflow_file.name}: failed to parse YAML: {e}")
                continue

        if not isinstance(data, dict):
            continue

        # PyYAML parses the top-level `on:` key as boolean True.
        triggers = data.get(True, data.get("on"))
        if not is_pr_triggered(triggers):
            continue

        if "concurrency" not in data:
            errors.append(f"{workflow_file.name}: missing top-level concurrency block")

    return errors


def main() -> None:
    errors = check_concurrency()
    if errors:
        print(f"Found {len(errors)} PR-triggered workflow(s) missing concurrency:\n")
        for error in errors:
            print(f"  - {error}")
        print("\nFix by adding this block after `on:`:\n")
        print("concurrency:")
        print("    group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}")
        print("    cancel-in-progress: ${{ github.event_name == 'pull_request' }}")
        print("\nOr, if cancelling stale runs would lose data (telemetry, schedule-only PR triggers, etc.),")
        print(f"add the filename to the SKIP set in {Path(__file__).name} with a one-line reason.")
        sys.exit(1)
    else:
        print("All PR-triggered ci-*.yml workflows have concurrency configured.")


if __name__ == "__main__":
    main()
