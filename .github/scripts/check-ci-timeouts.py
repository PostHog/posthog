#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
CI script to verify all GitHub Actions jobs declare timeout-minutes.

Without explicit timeout-minutes, jobs default to a 6-hour execution limit,
meaning stuck runners silently burn CI credits.

Usage:
    uv run .github/scripts/check-ci-timeouts.py
"""

import sys
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"


def check_timeouts() -> list[str]:
    errors: list[str] = []
    for workflow_file in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
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
            # Reusable workflow calls (jobs with `uses:`) don't support
            # timeout-minutes at the job level — timeouts are set inside
            # the called workflow.
            if "uses" in job_config:
                continue
            if "timeout-minutes" not in job_config:
                errors.append(f"{workflow_file.name}: job '{job_name}' is missing timeout-minutes")

    return errors


def main() -> None:
    errors = check_timeouts()
    if errors:
        print(f"Found {len(errors)} job(s) missing timeout-minutes:\n")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print("All jobs have timeout-minutes set.")


if __name__ == "__main__":
    main()
