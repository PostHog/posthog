from __future__ import annotations

import os
import sys
import json
import argparse
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DecisionAction(StrEnum):
    RERUN = "rerun"
    SKIP_DISABLED = "skip disabled"
    SKIP_CAP_REACHED = "skip cap reached"
    SKIP_NOT_INFRA = "skip not infra"


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    name: str
    conclusion: str | None
    run_attempt: int
    html_url: str


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    conclusion: str | None
    runner_name: str | None
    html_url: str


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    job: Job
    reason: str


DEPOT_STEP_CANCELED_MARKERS = (
    "Step canceled by GitHub",
    "depot.dev/docs/github-actions/troubleshooting#error-step-canceled-by-github",
)

ELIGIBLE_WORKFLOW_CONCLUSIONS = {"failure", "cancelled", "timed_out"}
ELIGIBLE_JOB_CONCLUSIONS = {"failure", "cancelled", "timed_out"}


def as_bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def load_workflow_run(event_path: Path) -> WorkflowRun:
    payload = json.loads(event_path.read_text())
    raw_run = payload.get("workflow_run")
    if not isinstance(raw_run, dict):
        raise ValueError("event payload does not contain workflow_run")

    return WorkflowRun(
        id=int(raw_run["id"]),
        name=str(raw_run.get("name") or ""),
        conclusion=str(raw_run.get("conclusion") or ""),
        run_attempt=int(raw_run.get("run_attempt") or 1),
        html_url=str(raw_run.get("html_url") or ""),
    )


def parse_job(raw_job: dict[str, object]) -> Job:
    return Job(
        id=int(raw_job["id"]),
        name=str(raw_job.get("name") or ""),
        conclusion=str(raw_job.get("conclusion") or ""),
        runner_name=str(raw_job["runner_name"]) if raw_job.get("runner_name") else None,
        html_url=str(raw_job.get("html_url") or ""),
    )


def classify_job(job: Job, log_text: str, run_attempt: int, max_reruns: int, enabled: bool) -> Decision:
    if job.conclusion not in ELIGIBLE_JOB_CONCLUSIONS:
        return Decision(DecisionAction.SKIP_NOT_INFRA, job, f"job conclusion is {job.conclusion or 'unknown'}")

    if not all(marker in log_text for marker in DEPOT_STEP_CANCELED_MARKERS):
        return Decision(DecisionAction.SKIP_NOT_INFRA, job, "no recognized Depot/GitHub cancellation marker")

    if job.runner_name is not None and not job.runner_name.startswith("depot-"):
        return Decision(DecisionAction.SKIP_NOT_INFRA, job, f"runner is {job.runner_name}, not a Depot runner")

    if run_attempt > max_reruns:
        return Decision(
            DecisionAction.SKIP_CAP_REACHED,
            job,
            f"workflow run attempt {run_attempt} is above automatic rerun cap {max_reruns}",
        )

    if not enabled:
        return Decision(DecisionAction.SKIP_DISABLED, job, "CI_INFRA_RETRY_ENABLED is false")

    return Decision(DecisionAction.RERUN, job, "matched Depot/GitHub infra cancellation marker")


def gh_json(path: str) -> dict[str, object]:
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True)
    raw = json.loads(result.stdout)
    if not isinstance(raw, dict):
        raise ValueError(f"expected object response from gh api {path}")
    return raw


def gh_text(path: str) -> str:
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True)
    return result.stdout


def gh_post(path: str) -> None:
    subprocess.run(["gh", "api", "--method", "POST", path], check=True, text=True)


def list_jobs(repo: str, run_id: int) -> list[Job]:
    jobs: list[Job] = []
    page = 1
    while True:
        data = gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}")
        raw_jobs = data.get("jobs")
        if not isinstance(raw_jobs, list):
            raise ValueError("jobs response did not contain a jobs list")
        jobs.extend(parse_job(job) for job in raw_jobs if isinstance(job, dict))

        total_count = int(data.get("total_count") or len(jobs))
        if len(jobs) >= total_count or not raw_jobs:
            return jobs
        page += 1


def get_job_log(repo: str, job_id: int) -> str:
    return gh_text(f"repos/{repo}/actions/jobs/{job_id}/logs")


def make_decisions(repo: str, workflow_run: WorkflowRun, enabled: bool, max_reruns: int) -> list[Decision]:
    if workflow_run.conclusion not in ELIGIBLE_WORKFLOW_CONCLUSIONS:
        sys.stdout.write(f"workflow conclusion is {workflow_run.conclusion or 'unknown'}; nothing to inspect\n")
        return []

    decisions: list[Decision] = []
    for job in list_jobs(repo, workflow_run.id):
        if job.conclusion not in ELIGIBLE_JOB_CONCLUSIONS:
            continue
        try:
            log_text = get_job_log(repo, job.id)
        except subprocess.CalledProcessError as exc:
            decisions.append(Decision(DecisionAction.SKIP_NOT_INFRA, job, f"could not fetch job log: {exc}"))
            continue
        decisions.append(classify_job(job, log_text, workflow_run.run_attempt, max_reruns, enabled))
    return decisions


def apply_decisions(repo: str, decisions: list[Decision], dry_run: bool) -> None:
    for decision in decisions:
        sys.stdout.write(f"{decision.action}: {decision.job.name} ({decision.job.html_url}) - {decision.reason}\n")
        if decision.action != DecisionAction.RERUN:
            continue
        if dry_run:
            sys.stdout.write(f"dry-run: would rerun job {decision.job.id}\n")
            continue
        gh_post(f"repos/{repo}/actions/jobs/{decision.job.id}/rerun")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rerun jobs that failed due to recognized GitHub/Depot infra cancellation."
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--enabled", action="store_true", default=as_bool(os.environ.get("CI_INFRA_RETRY_ENABLED")))
    parser.add_argument("--dry-run", action="store_true", default=as_bool(os.environ.get("CI_INFRA_RETRY_DRY_RUN")))
    parser.add_argument("--max-reruns", type=int, default=int(os.environ.get("CI_INFRA_RETRY_MAX_RERUNS", "1")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.repo:
        sys.stderr.write("GITHUB_REPOSITORY is required\n")
        return 2
    if not args.event_path:
        sys.stderr.write("GITHUB_EVENT_PATH is required\n")
        return 2

    try:
        workflow_run = load_workflow_run(Path(args.event_path))
        decisions = make_decisions(args.repo, workflow_run, args.enabled, args.max_reruns)
        apply_decisions(args.repo, decisions, args.dry_run)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"ci-infra-retry skipped: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
