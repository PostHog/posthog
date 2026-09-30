#!/usr/bin/env python3
"""Cancel the Backend CI runs on Depot CI that a later event of the same pull request superseded.

Depot's concurrency policy keeps the workflow it created last, and Depot can create an older
event's workflow after a newer one's. Runs keep event order, so this script orders by run.
A run cancels the older runs it sees, and cancels itself when it sees a newer one, so the run
whose workflow Depot creates last settles each pair.
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
    head_sha: str

    def supersedes(self, other: "Run") -> bool:
        # The run id cannot tell which of two commits is the PR's head, so a same-second tie between commits keeps both.
        if self.created_at != other.created_at:
            return self.created_at > other.created_at
        return self.head_sha == other.head_sha and self.run_id > other.run_id


@dataclass(frozen=True, kw_only=True, slots=True)
class Workflow:
    workflow_id: str
    run_id: str
    path: str


def superseded(own_workflow_id: str, active_workflows: Sequence[Workflow], runs: Sequence[Run]) -> list[Workflow]:
    runs_by_id = {run.run_id: run for run in runs}
    own = {workflow.workflow_id: workflow for workflow in active_workflows}[own_workflow_id]
    me = runs_by_id[own.run_id]
    if any(run.supersedes(me) for run in runs):
        return [own]
    return [
        workflow
        for workflow in active_workflows
        if workflow.path == WORKFLOW_PATH
        and workflow.run_id in runs_by_id
        and me.supersedes(runs_by_id[workflow.run_id])
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
            Run(run_id=row["run_id"], created_at=datetime.fromisoformat(row["created_at"]), head_sha=row["head_sha"])
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
