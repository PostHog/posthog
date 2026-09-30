#!/usr/bin/env python3
"""Cancel the Backend CI runs on Depot CI that a later event of the same pull request superseded.

Depot's concurrency policy keeps the workflow it created last, and Depot can create an older
event's workflow after a newer one's. Runs keep event order, so this script orders by run.
See "Superseded runs" in .agents/skills/depot-ci/references/posthog-check-run-semantics.md.

Standard library only: the job runs this with the runner's python3 before any install.
"""

import os
import re
import sys
import json
import time
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

WORKFLOW_PATH = "ci-backend.yml"
ACTIVE = ("queued", "running")
DEPOT_JOB_URL = re.compile(r"^https://depot\.dev/orgs/[^/?]+/workflows/([a-z0-9]+)")
ATTEMPTS = 12
POLL_SECONDS = 15


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
    status: str


@dataclass(frozen=True, kw_only=True, slots=True)
class Plan:
    cancel: tuple[Workflow, ...]
    # An older run can exist before Depot creates its workflow, so there is nothing to cancel yet.
    waiting: bool


def plan(own_workflow_id: str, workflows: Sequence[Workflow], active_runs: Sequence[Run]) -> Plan:
    runs = {run.run_id: run for run in active_runs}
    own = next((workflow for workflow in workflows if workflow.workflow_id == own_workflow_id), None)
    me = runs.get(own.run_id) if own else None
    if me is None:
        return Plan(cancel=(), waiting=True)
    older = {run.run_id for run in active_runs if me.supersedes(run)}
    return Plan(
        cancel=tuple(
            workflow
            for workflow in workflows
            if workflow.run_id in older and workflow.path == WORKFLOW_PATH and workflow.status in ACTIVE
        ),
        waiting=bool(older - {workflow.run_id for workflow in workflows}),
    )


class Depot(Protocol):
    def workflows(self) -> list[Workflow]: ...
    def active_runs(self) -> list[Run]: ...
    def cancel(self, workflow: Workflow) -> None: ...


class DepotCli:
    def __init__(self, repo: str, pr_number: str) -> None:
        self._scope = ["--repo", repo, "--pr", pr_number, "--trigger", "pull_request", "-n", "200", "-o", "json"]

    def workflows(self) -> list[Workflow]:
        statuses = [flag for status in (*ACTIVE, "finished", "failed", "cancelled") for flag in ("--status", status)]
        return [
            Workflow(
                workflow_id=row["workflow_id"], run_id=row["run_id"], path=row["workflow_path"], status=row["status"]
            )
            for row in self._list("workflow", statuses)
        ]

    def active_runs(self) -> list[Run]:
        statuses = [flag for status in ACTIVE for flag in ("--status", status)]
        return [
            Run(run_id=row["run_id"], created_at=datetime.fromisoformat(row["created_at"]), head_sha=row["head_sha"])
            for row in self._list("run", statuses)
        ]

    def cancel(self, workflow: Workflow) -> None:
        sys.stdout.write(f"Cancelling superseded run {workflow.run_id} (workflow {workflow.workflow_id})\n")
        try:
            subprocess.run(["depot", "ci", "cancel", workflow.run_id, "--workflow", workflow.workflow_id], check=True)
        except subprocess.CalledProcessError:
            sys.stdout.write(f"::warning::Could not cancel run {workflow.run_id}\n")

    def _list(self, noun: str, statuses: list[str]) -> list[dict[str, str]]:
        command = ["depot", "ci", noun, "list", *self._scope, *statuses]
        # `depot ci run list` prints `null` when nothing matches.
        return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout) or []


def cancel_superseded(depot: Depot, own_workflow_id: str, sleep: Callable[[float], None] = time.sleep) -> bool:
    """False when an older run never got a workflow to cancel."""
    for attempt in range(ATTEMPTS):
        # Workflows first, so the run of every listed workflow is in the run list.
        workflows = depot.workflows()
        current = plan(own_workflow_id, workflows, depot.active_runs())
        for workflow in current.cancel:
            depot.cancel(workflow)
        if not current.waiting:
            return True
        if attempt < ATTEMPTS - 1:
            sleep(POLL_SECONDS)
    return False


def main() -> int:
    match = DEPOT_JOB_URL.match(os.environ.get("DEPOT_JOB_URL", ""))
    if not match:
        sys.stdout.write("::warning::DEPOT_JOB_URL names no workflow, so no run was cancelled.\n")
        return 0
    try:
        done = cancel_superseded(DepotCli(os.environ["REPO"], os.environ["PR_NUMBER"]), match[1])
    except (subprocess.CalledProcessError, KeyError, ValueError) as error:
        sys.stdout.write(f"::warning::Could not read this PR's Depot runs, so no run was cancelled: {error}\n")
        return 0
    if not done:
        sys.stdout.write("::warning::An older run of this PR still had no workflow to cancel.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
