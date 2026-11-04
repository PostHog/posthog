#!/usr/bin/env python3
"""Retry the failed and cancelled jobs of a pull request's newest Depot CI run.

.github/workflows/depot-retry-on-comment.yml runs this for a `/depot retry` comment.
See "Reruns" in .agents/skills/depot-ci/references/posthog-check-run-semantics.md.

Standard library only: the job runs this with the runner's python3 before any install.
"""

import os
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from cancel_superseded_depot_runs import ALL, depot, list_pr

RETRYABLE = ("failed", "cancelled")


def newest_run_id(runs: Sequence[dict[str, str]]) -> str | None:
    # Run ids are random, so they cannot break a same-second tie. max() keeps the first of equal
    # times, and `depot ci run list` lists the newest run first.
    newest = max(runs, key=lambda run: datetime.fromisoformat(run["created_at"]), default=None)
    return newest["run_id"] if newest else None


def retryable_workflow_ids(status: dict[str, Any]) -> list[str]:
    return [
        workflow["workflow_id"]
        for workflow in status.get("workflows") or []
        if any(job["status"] in RETRYABLE for job in workflow.get("jobs") or [])
    ]


def main() -> None:
    repo, pr_number = os.environ["REPO"], os.environ["PR_NUMBER"]
    run_id = newest_run_id(list_pr("run", repo, pr_number, ALL))
    if not run_id:
        sys.stdout.write(f"::notice::PR {pr_number} has no Depot run to retry.\n")
        return
    # A run that has no workflow yet has a `null` status.
    workflow_ids = retryable_workflow_ids(depot("status", run_id, "-o", "json") or {})
    for workflow_id in workflow_ids:
        sys.stdout.write(f"Retrying the failed and cancelled jobs of run {run_id} (workflow {workflow_id})\n")
        depot("retry", run_id, "--failed", "--workflow", workflow_id, "-o", "json")
    if not workflow_ids:
        sys.stdout.write(f"::notice::PR {pr_number} has no failed or cancelled Depot jobs to retry.\n")


if __name__ == "__main__":
    main()
