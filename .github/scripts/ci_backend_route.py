#!/usr/bin/env python3
"""Decide which CI engine runs a Backend CI event: GitHub Actions or Depot CI.

Only GitHub Actions runs this script. Its answer drives the `Hand off backend tests
to Depot CI` job, which Depot CI waits for before it runs anything, so Depot never
routes on its own and the tests never run on both engines. Once that job has concluded
for a commit, every later run of the same commit repeats its answer, whatever the
percent or the labels say by then.
"""

import os
import sys
import json
from dataclasses import dataclass

LABEL_FORCE_GITHUB = "ci-backend-github"
LABEL_FORCE_DEPOT = "ci-backend-depot"
PERCENT_VARIABLE = "CI_BACKEND_DEPOT_PERCENT"


@dataclass(frozen=True)
class Decision:
    engine: str
    reason: str


def parse_percent(raw: str | None) -> int:
    value = raw.strip() if raw is not None else ""
    if not value.isascii() or not value.isdecimal():
        return 0
    try:
        return min(int(value), 100)
    except ValueError:
        return 0


def decide(
    event: str,
    percent: int,
    pr_number: int | None,
    labels: list[str],
    is_fork: bool,
    is_draft: bool,
    prior_engine: str | None = None,
) -> Decision:
    if event != "pull_request":
        return Decision("github", f"{event} events stay on GitHub Actions")
    if prior_engine in ("depot", "github"):
        return Decision(prior_engine, f"an earlier run of this commit chose {prior_engine}")
    if LABEL_FORCE_GITHUB in labels:
        return Decision("github", f"label {LABEL_FORCE_GITHUB}")
    if is_fork:
        return Decision("github", "fork pull requests never run on Depot")
    if is_draft and "no-ci" in labels:
        return Decision("github", "no-ci drafts skip on GitHub Actions and run nowhere else")
    if LABEL_FORCE_DEPOT in labels:
        return Decision("depot", f"label {LABEL_FORCE_DEPOT}")
    if pr_number is None:
        return Decision("github", "no pull request number to hash")
    bucket = pr_number % 100
    if bucket < percent:
        return Decision("depot", f"bucket {bucket} < {percent}%")
    return Decision("github", f"bucket {bucket} >= {percent}%")


def main() -> int:
    env = os.environ
    pr_raw = env.get("PR_NUMBER", "")
    decision = decide(
        event=env.get("EVENT", ""),
        percent=parse_percent(env.get("PERCENT")),
        pr_number=int(pr_raw) if pr_raw.isdigit() else None,
        labels=json.loads(env.get("LABELS") or "[]") or [],
        is_fork=env.get("IS_FORK", "false") == "true",
        is_draft=env.get("IS_DRAFT", "false") == "true",
        prior_engine=env.get("PRIOR_ENGINE") or None,
    )
    sys.stdout.write(f"::notice::Backend CI engine: {decision.engine} ({decision.reason})\n")
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"engine={decision.engine}\nreason={decision.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
