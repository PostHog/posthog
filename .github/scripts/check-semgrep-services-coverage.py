#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# ruff: noqa: T201 allow print statements
"""
CI script to verify every services/<name>/ is covered by a language-specific
Semgrep job in .github/workflows/ci-security.yaml.

The repo-wide semgrep-general job excludes services/, so a new service added
without updating semgrep-python or semgrep-js silently drops out of SAST.

Usage:
    uv run .github/scripts/check-semgrep-services-coverage.py
"""

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = REPO_ROOT / "services"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-security.yaml"
COVERING_JOBS = ("semgrep-python", "semgrep-js")


def services_subdirs() -> list[str]:
    return sorted(p.name for p in SERVICES_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def covering_run_text() -> str:
    with open(SECURITY_WORKFLOW) as f:
        data = yaml.safe_load(f)

    jobs = data.get("jobs", {})
    parts: list[str] = []
    for job_name in COVERING_JOBS:
        job = jobs.get(job_name)
        if not isinstance(job, dict):
            raise SystemExit(f"{SECURITY_WORKFLOW.name}: expected job '{job_name}'")
        for step in job.get("steps", []) or []:
            run = step.get("run") if isinstance(step, dict) else None
            if isinstance(run, str):
                parts.append(run)
    return "\n".join(parts)


def main() -> None:
    text = covering_run_text()
    all_services = services_subdirs()
    missing = [name for name in all_services if f"services/{name}/" not in text]

    if missing:
        print(
            f"Found {len(missing)} service(s) not covered by {' or '.join(COVERING_JOBS)} "
            f"in {SECURITY_WORKFLOW.name}:\n"
        )
        for name in missing:
            print(f"  - services/{name}/")
        print("\nAdd each to the matching job's target list in ci-security.yaml.")
        sys.exit(1)

    print(f"All {len(all_services)} service(s) covered by Semgrep scans.")


if __name__ == "__main__":
    main()
