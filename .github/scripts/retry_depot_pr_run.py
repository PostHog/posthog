#!/usr/bin/env python3
"""Retry the failed and cancelled jobs of a pull request's newest Depot CI run.

.depot/workflows/retry-on-comment.yml runs this for a `/retry` comment. `depot ci retry --failed`
works while the rest of the run is still going, and it also reruns the jobs downstream of each
retried job, so the gate reports the new result. GitHub's Re-run button on a Depot check sends its
request only to Depot's own GitHub App, which does not act on it.

Standard library only: the job runs this with the runner's python3 before any install.
"""

import os
import sys
import json
import subprocess
from collections.abc import Sequence
from typing import Any

RETRYABLE = ("failed", "cancelled")
ALL_STATUSES = ("queued", "running", "finished", *RETRYABLE)
CLI_TIMEOUT_SECONDS = 60


def newest_run_id(runs: Sequence[dict[str, str]]) -> str | None:
    # Depot runs keep event order, and the run id breaks a same-second tie.
    newest = max(runs, key=lambda run: (run["created_at"], run["run_id"]), default=None)
    return newest["run_id"] if newest else None


def retryable_workflow_ids(status: dict[str, Any]) -> list[str]:
    return [
        workflow["workflow_id"]
        for workflow in status.get("workflows") or []
        if any(job["status"] in RETRYABLE for job in workflow.get("jobs") or [])
    ]


def depot(*args: str) -> Any:
    # stderr passes through, so a failed call explains itself in the job log.
    result = subprocess.run(
        ["depot", "ci", *args, "-o", "json"], check=True, stdout=subprocess.PIPE, text=True, timeout=CLI_TIMEOUT_SECONDS
    )
    # `depot ci run list` prints `null` when nothing matches.
    return json.loads(result.stdout) or []


def main() -> int:
    repo, pr_number = os.environ["REPO"], os.environ["PR_NUMBER"]
    statuses = (flag for status in ALL_STATUSES for flag in ("--status", status))
    run_id = newest_run_id(
        depot("run", "list", "--repo", repo, "--pr", pr_number, "--trigger", "pull_request", "-n", "200", *statuses)
    )
    workflow_ids = retryable_workflow_ids(depot("status", run_id)) if run_id else []
    for workflow_id in workflow_ids:
        sys.stdout.write(f"Retrying the failed and cancelled jobs of run {run_id} (workflow {workflow_id})\n")
        depot("retry", run_id, "--failed", "--workflow", workflow_id)
    if not workflow_ids:
        sys.stdout.write(f"::notice::PR {pr_number} has no failed or cancelled Depot jobs to retry.\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"retried={len(workflow_ids)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
