#!/usr/bin/env python3
"""Cancel the Backend CI runs on Depot CI that a later event of the same pull request superseded.

GitHub Actions runs this script in the pull request event it kept. Its concurrency group keeps one
run per pull request, so every Depot run created before this event belongs to an event GitHub
Actions already dropped. Depot creates each run after its own event, so this event's run and any
later one are never touched. GitHub Actions makes the decision, and Depot never orders runs itself.
See "Superseded runs" in .agents/skills/depot-ci/references/posthog-check-run-semantics.md.

Standard library only: the job runs this with the runner's python3 before any install.
"""

import os
import sys
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

WORKFLOW_PATH = "ci-backend.yml"
ACTIVE = ("queued", "running")
ALL = (*ACTIVE, "finished", "failed", "cancelled")
CLI_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, kw_only=True, slots=True)
class Run:
    run_id: str
    created_at: datetime


@dataclass(frozen=True, kw_only=True, slots=True)
class Workflow:
    workflow_id: str
    run_id: str
    path: str


def superseded(event_at: datetime, active_workflows: Sequence[Workflow], runs: Sequence[Run]) -> list[Workflow]:
    created = {run.run_id: run.created_at for run in runs}
    return [
        workflow
        for workflow in active_workflows
        if workflow.path == WORKFLOW_PATH and workflow.run_id in created and created[workflow.run_id] < event_at
    ]


def depot(*args: str) -> list[dict[str, str]]:
    result = subprocess.run(
        ["depot", "ci", *args], check=True, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS
    )
    # `depot ci run list` prints `null` when nothing matches.
    return json.loads(result.stdout) or []


def list_pr(noun: str, repo: str, pr_number: str, statuses: Sequence[str]) -> list[dict[str, str]]:
    scope = ["--repo", repo, "--pr", pr_number, "--trigger", "pull_request", "-n", "200", "-o", "json"]
    return depot(noun, "list", *scope, *(flag for status in statuses for flag in ("--status", status)))


def main() -> int:
    repo, pr_number = os.environ["REPO"], os.environ["PR_NUMBER"]
    try:
        event_at = datetime.fromisoformat(os.environ["EVENT_AT"])
        # Workflows first, so the run of every listed workflow is in the run list.
        workflows = [
            Workflow(workflow_id=row["workflow_id"], run_id=row["run_id"], path=row["workflow_path"])
            for row in list_pr("workflow", repo, pr_number, ACTIVE)
        ]
        runs = [
            Run(run_id=row["run_id"], created_at=datetime.fromisoformat(row["created_at"]))
            for row in list_pr("run", repo, pr_number, ALL)
        ]
        targets = superseded(event_at, workflows, runs)
    except (subprocess.SubprocessError, KeyError, ValueError) as error:
        sys.stdout.write(f"::warning::Could not read this PR's Depot runs, so no run was cancelled: {error!r}\n")
        return 0
    for workflow in targets:
        sys.stdout.write(f"Cancelling superseded run {workflow.run_id} (workflow {workflow.workflow_id})\n")
        try:
            subprocess.run(
                ["depot", "ci", "cancel", workflow.run_id, "--workflow", workflow.workflow_id],
                check=True,
                timeout=CLI_TIMEOUT_SECONDS,
            )
        except subprocess.SubprocessError:
            sys.stdout.write(f"::warning::Could not cancel run {workflow.run_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
