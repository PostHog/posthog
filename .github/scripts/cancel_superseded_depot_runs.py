#!/usr/bin/env python3
"""Cancel the Backend CI runs on Depot CI that a later event of the same pull request superseded.

Only a run that GitHub Actions handed off runs this script. GitHub Actions keeps one run per pull
request and cancels the others within seconds, long before any hand-off, so the handed-off run
is the event GitHub Actions kept. The script never cancels its own run: an order Depot sees can
disagree with the one GitHub Actions kept. It cancels every other run of the pull request that
Depot created at the same time or earlier. A newer run is left alone, and cancels this one once
it is handed off.
See "Superseded runs" in .agents/skills/depot-ci/references/posthog-check-run-semantics.md.

Standard library only: the job runs this with the runner's python3 before any install.
"""

import os
import re
import sys
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

WORKFLOW_PATH = "ci-backend.yml"
ACTIVE = ("queued", "running")
ALL = (*ACTIVE, "finished", "failed", "cancelled")
DEPOT_JOB_URL = re.compile(r"^https://depot\.dev/orgs/[^/?]+/workflows/([a-z0-9]+)")
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


def superseded(own_workflow_id: str, active_workflows: Sequence[Workflow], runs: Sequence[Run]) -> list[Workflow]:
    runs_by_id = {run.run_id: run for run in runs}
    own = {workflow.workflow_id: workflow for workflow in active_workflows}[own_workflow_id]
    me = runs_by_id[own.run_id]
    return [
        workflow
        for workflow in active_workflows
        if workflow.path == WORKFLOW_PATH
        and workflow.run_id != me.run_id
        and workflow.run_id in runs_by_id
        and runs_by_id[workflow.run_id].created_at <= me.created_at
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
    match = DEPOT_JOB_URL.match(os.environ.get("DEPOT_JOB_URL", ""))
    if not match:
        sys.stdout.write("::warning::DEPOT_JOB_URL names no workflow, so no run was cancelled.\n")
        return 0
    repo, pr_number = os.environ["REPO"], os.environ["PR_NUMBER"]
    try:
        # Workflows first, so the run of every listed workflow is in the run list.
        workflows = [
            Workflow(workflow_id=row["workflow_id"], run_id=row["run_id"], path=row["workflow_path"])
            for row in list_pr("workflow", repo, pr_number, ACTIVE)
        ]
        runs = [
            Run(run_id=row["run_id"], created_at=datetime.fromisoformat(row["created_at"]))
            for row in list_pr("run", repo, pr_number, ALL)
        ]
        targets = superseded(match[1], workflows, runs)
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
