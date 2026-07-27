#!/usr/bin/env python3
# ruff: noqa: T201 - CLI output is the contract for this script.

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

JsonObject = dict[str, object]
# Observe-only: we classify failed CI jobs and record what reruns do, but never rerun anything.
DecisionAction = Literal["observe", "skip deterministic", "skip non-test"]

DEFAULT_ALLOWED_WORKFLOWS = ("Backend CI", "Dagster CI", "E2E CI Playwright")
DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
DECISION_EVENT = "ci_flake_overseer_decision"
OUTCOME_EVENT = "ci_flake_overseer_rerun_outcome"


def compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


def compile_classified(*rules: tuple[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern, re.IGNORECASE), failure_class) for pattern, failure_class in rules)


# Jobs/steps whose failures a rerun can't fix — excluded from the flake measurement.
# Each rule carries a stable failure-class key (matching `hogli ci:preflight` check
# keys where the two overlap) so dashboards can group deterministic failures that
# reached CI and join them against local preflight interceptions.
DETERMINISTIC_JOB_RULES = compile_classified(
    (r"\brepo checks?\b", "repo-checks"),
    (r"\bopenapi\b", "openapi"),
    (r"\bmigrations?\b", "migrations"),
    (r"\blint\b", "lint"),
    (r"\btype ?check\b", "typecheck"),
    (r"\btypescript\b", "typecheck"),
    (r"\bvisual\b", "visual-review"),
    (r"\bsnapshot\b", "snapshot"),
    (r"\bstorybook\b", "storybook"),
    (r"\btach\b", "module-boundaries"),
    (r"\bimport-linter\b", "module-boundaries"),
)

DETERMINISTIC_STEP_RULES = compile_classified(
    (r"\bcheck module boundaries\b", "module-boundaries"),
    (r"\bproduct facade enforcement\b", "module-boundaries"),
    (r"\bopenapi\b", "openapi"),
    (r"\bmigrations?\b", "migrations"),
    (r"\blint\b", "lint"),
    (r"\btype ?check\b", "typecheck"),
    (r"\btypescript\b", "typecheck"),
    (r"\bvisual review\b", "visual-review"),
    (r"\bsnapshot\b", "snapshot"),
    (r"\bverify changed playwright tests are stable\b", "playwright-stability"),
    (r"\bverify new snapshots\b", "snapshot"),
)

TEST_STEP_PATTERNS = compile_patterns(
    r"\brun core tests\b",
    r"\brun temporal tests\b",
    r"\brun product tests\b",
    r"\brun dagster tests\b",
    r"\brun playwright tests\b",
)

TEST_JOB_PATTERNS = compile_patterns(
    r"\bdjango tests\b",
    r"\bproduct tests\b",
    r"\bdagster tests\b",
    r"\bplaywright e2e tests\b",
)


class ExternalCommandError(Exception):
    pass


@dataclass(frozen=True)
class Step:
    name: str
    conclusion: str | None


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    conclusion: str | None
    run_attempt: int
    html_url: str
    # A genuine re-run advances started_at; a carried-over job keeps the prior attempt's value byte-for-byte
    # (run_attempt reports the latest attempt for every job either way), so started_at is the re-run signal.
    started_at: str | None = None
    steps: tuple[Step, ...] = ()

    def failed_step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if step.conclusion in {"failure", "timed_out"})


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    workflow_id: int
    name: str
    conclusion: str | None
    head_sha: str
    run_attempt: int
    html_url: str
    head_branch: str = ""
    event: str = ""
    # Empty `pull_requests` (e.g. fork PRs) collapses to None; head_branch stays the primary join key.
    pr_number: int | None = None


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    reason: str
    job: Job
    # Which signal classified an `observe`: the job name or a failed step. Surfaces silent allowlist drift.
    classified_via: str | None = None
    # Canonical failure-class key for `skip deterministic` decisions (see the rule tables above).
    failure_class: str | None = None


def as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def as_object(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def as_object_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [cast(JsonObject, item) for item in value if isinstance(item, dict)]


def as_bool_string(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def run_command(args: tuple[str, ...], timeout_seconds: int = 30) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ExternalCommandError(str(exc)) from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "command failed"
        raise ExternalCommandError(message)
    return result.stdout


def gh_json(repo: str, path: str) -> JsonObject:
    raw = run_command(("gh", "api", f"repos/{repo}/{path}"), timeout_seconds=45)
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def pr_number_from_object(raw: JsonObject) -> int | None:
    pulls = as_object_list(raw.get("pull_requests"))
    return as_int(pulls[0].get("number")) if pulls else None


def workflow_run_from_object(raw: JsonObject) -> WorkflowRun:
    return WorkflowRun(
        id=as_int(raw.get("id")) or 0,
        workflow_id=as_int(raw.get("workflow_id")) or 0,
        name=as_str(raw.get("name")) or as_str(raw.get("workflow_name")) or "",
        conclusion=as_str(raw.get("conclusion")),
        head_sha=as_str(raw.get("head_sha")) or "",
        run_attempt=as_int(raw.get("run_attempt")) or 1,
        html_url=as_str(raw.get("html_url")) or "",
        head_branch=as_str(raw.get("head_branch")) or "",
        event=as_str(raw.get("event")) or "",
        pr_number=pr_number_from_object(raw),
    )


def workflow_run_from_event(path: Path) -> WorkflowRun | None:
    try:
        parsed = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    workflow_run = as_object(parsed.get("workflow_run"))
    return workflow_run_from_object(workflow_run) if workflow_run else None


def job_from_object(raw: JsonObject, run_attempt: int) -> Job:
    return Job(
        id=as_int(raw.get("id")) or 0,
        name=as_str(raw.get("name")) or "",
        conclusion=as_str(raw.get("conclusion")),
        # Trust the job's own attempt over the requested one — the fallback endpoint returns the latest attempt.
        run_attempt=as_int(raw.get("run_attempt")) or run_attempt,
        html_url=as_str(raw.get("html_url")) or "",
        started_at=as_str(raw.get("started_at")),
        steps=tuple(
            Step(name=as_str(step.get("name")) or "", conclusion=as_str(step.get("conclusion")))
            for step in as_object_list(raw.get("steps"))
        ),
    )


def fetch_jobs(repo: str, run_id: int, run_attempt: int, *, strict: bool = False) -> tuple[Job, ...]:
    jobs: list[Job] = []
    page = 1
    while True:
        try:
            raw = gh_json(repo, f"actions/runs/{run_id}/attempts/{run_attempt}/jobs?per_page=100&page={page}")
        except ExternalCommandError:
            # The non-attempt endpoint returns the LATEST attempt, so it can't stand in for an arbitrary
            # prior attempt. Strict callers need exact rows, so fail closed (drop any partial pages) rather
            # than return a truncated set or a masquerading attempt.
            if strict:
                return ()
            raw = gh_json(repo, f"actions/runs/{run_id}/jobs?per_page=100&page={page}")
        page_jobs = as_object_list(raw.get("jobs"))
        jobs.extend(job_from_object(job, run_attempt) for job in page_jobs)
        if len(page_jobs) < 100:
            return tuple(jobs)
        page += 1


def deterministic_match(job: Job) -> tuple[str, str] | None:
    for pattern, failure_class in DETERMINISTIC_JOB_RULES:
        if pattern.search(job.name):
            return f"job name matches deterministic rule `{pattern.pattern}`", failure_class
    for step_name in job.failed_step_names():
        for pattern, failure_class in DETERMINISTIC_STEP_RULES:
            if pattern.search(step_name):
                return f"failed step `{step_name}` matches deterministic rule `{pattern.pattern}`", failure_class
    return None


def test_failure_source(job: Job) -> str | None:
    if any(pattern.search(job.name) for pattern in TEST_JOB_PATTERNS):
        return "job_name"
    if any(pattern.search(step_name) for step_name in job.failed_step_names() for pattern in TEST_STEP_PATTERNS):
        return "step"
    return None


def is_test_job_failure(job: Job) -> bool:
    return test_failure_source(job) is not None


def classify_job(job: Job) -> Decision:
    deterministic = deterministic_match(job)
    if deterministic is not None:
        reason, failure_class = deterministic
        return Decision(action="skip deterministic", reason=reason, job=job, failure_class=failure_class)
    source = test_failure_source(job)
    if source is None:
        return Decision(action="skip non-test", reason="failed job or step is not an allowlisted test runner", job=job)
    return Decision(
        action="observe", reason="test job failure tracked for rerun outcome", job=job, classified_via=source
    )


def classify_failed_jobs(repo: str, run_id: int, run_attempt: int) -> tuple[Decision, ...]:
    return tuple(
        classify_job(job) for job in fetch_jobs(repo, run_id, run_attempt) if job.conclusion in {"failure", "timed_out"}
    )


def base_event_properties(repo: str, workflow_run: WorkflowRun) -> JsonObject:
    return {
        "repo": repo,
        "workflow_name": workflow_run.name,
        "run_id": workflow_run.id,
        "run_url": workflow_run.html_url,
        "head_sha": workflow_run.head_sha,
        "head_branch": workflow_run.head_branch,
        "pr_number": workflow_run.pr_number,
        # Master failures block the deploy gate; PR failures only annoy the author — keep them separable.
        "is_master": workflow_run.head_branch in {"master", "main"},
        "trigger_event": workflow_run.event,
        # Reuse the project's existing workflow_run group so events roll up per CI run.
        "$groups": {"workflow_run": str(workflow_run.id)},
    }


def build_decision_events(repo: str, workflow_run: WorkflowRun, decisions: tuple[Decision, ...]) -> list[JsonObject]:
    events: list[JsonObject] = []
    for decision in decisions:
        job = decision.job
        properties = base_event_properties(repo, workflow_run)
        properties.update(
            {
                "action": decision.action,
                "reason": decision.reason,
                "classified_via": decision.classified_via,
                "failure_class": decision.failure_class,
                "job_name": job.name,
                "job_id": job.id,
                "job_url": job.html_url,
                "job_conclusion": job.conclusion,
                "failed_steps": list(job.failed_step_names()),
                "run_attempt": job.run_attempt,
                # Dedupe duplicate workflow_run deliveries so the count panels stay accurate.
                "$insert_id": f"decision:{workflow_run.id}:{workflow_run.run_attempt}:{job.id}",
            }
        )
        events.append({"event": DECISION_EVENT, "distinct_id": repo, "properties": properties})
    return events


def rerun_outcome_label(conclusion: str | None) -> str:
    if conclusion == "success":
        return "cleared"
    if conclusion in {"failure", "timed_out"}:
        return "still_failing"
    return "unknown"


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Normalize a trailing `Z` for parsers that don't accept the military-zulu suffix.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def job_was_reexecuted(prior_job: Job, current_job: Job) -> bool:
    # A real re-run advances started_at; a carried-over job keeps the prior attempt's value. Compare parsed
    # instants, not raw strings, so a `+00:00` vs `Z` form can't misorder. Missing/unparseable timestamps
    # can't prove re-execution, so treat them as not re-run rather than guess.
    prior = parse_timestamp(prior_job.started_at)
    current = parse_timestamp(current_job.started_at)
    if prior is None or current is None:
        return False
    return current > prior


def rerun_outcome(prior_job: Job, current_job: Job | None) -> str:
    # `current_job is None` covers a job missing from the current attempt or an ambiguous (duplicated) name.
    if current_job is None:
        return "unknown"
    if not job_was_reexecuted(prior_job, current_job):
        return "not_rerun"
    return rerun_outcome_label(current_job.conclusion)


def index_unique_jobs_by_name(jobs: tuple[Job, ...]) -> dict[str, Job]:
    # Job names are unique within an attempt; if one ever repeats, drop it so an ambiguous match becomes
    # `unknown` instead of silently picking the wrong row.
    by_name: dict[str, Job] = {}
    ambiguous: set[str] = set()
    for job in jobs:
        if job.name in by_name:
            ambiguous.add(job.name)
        by_name[job.name] = job
    for name in ambiguous:
        by_name.pop(name, None)
    return by_name


def report_rerun_outcomes(repo: str, workflow_run: WorkflowRun) -> list[JsonObject]:
    # Outcomes only exist once a re-run attempt has completed. Find the test-job failures from the prior
    # attempt, then read how they concluded this attempt — the base-rate signal: do reruns clear flakes?
    if workflow_run.run_attempt <= 1:
        return []
    prior_attempt = workflow_run.run_attempt - 1
    # Fetch the prior attempt strict: the non-attempt fallback returns the LATEST attempt, which would alias
    # as "prior" and collapse the started_at re-execution check. The current attempt IS the latest, so it
    # keeps the fallback (the non-attempt endpoint returns it correctly). Both sides dedupe ambiguous names.
    prior_observed = {
        name: job
        for name, job in index_unique_jobs_by_name(
            fetch_jobs(repo, workflow_run.id, prior_attempt, strict=True)
        ).items()
        if job.conclusion in {"failure", "timed_out"} and classify_job(job).action == "observe"
    }
    if not prior_observed:
        return []
    current_by_name = index_unique_jobs_by_name(fetch_jobs(repo, workflow_run.id, workflow_run.run_attempt))
    events: list[JsonObject] = []
    for job_name in sorted(prior_observed):
        prior_job = prior_observed[job_name]
        current_job = current_by_name.get(job_name)
        properties = base_event_properties(repo, workflow_run)
        properties.update(
            {
                "outcome": rerun_outcome(prior_job, current_job),
                "current_conclusion": current_job.conclusion if current_job else None,
                "prior_conclusion": prior_job.conclusion,
                "job_name": job_name,
                "failed_steps": list(prior_job.failed_step_names()),
                "prior_attempt": prior_attempt,
                "attempt": workflow_run.run_attempt,
                # Dedupe duplicate workflow_run deliveries so the base-rate counts stay accurate.
                "$insert_id": f"outcome:{workflow_run.id}:{workflow_run.run_attempt}:{job_name}",
            }
        )
        events.append({"event": OUTCOME_EVENT, "distinct_id": repo, "properties": properties})
    return events


def capture_events(api_key: str, host: str, events: list[JsonObject], timeout_seconds: int = 10) -> None:
    if not api_key or not events:
        return
    payload = json.dumps({"api_key": api_key, "batch": events}).encode()
    request = urllib.request.Request(
        f"{host.rstrip('/')}/batch/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- host is CI config, not request input
        with urllib.request.urlopen(request, timeout=timeout_seconds):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"::warning title=CI flake overseer telemetry failed::{escape_annotation(str(exc))}")


def escape_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def markdown_link(label: str, url: str) -> str:
    safe_label = escape_table(label)
    return f"[{safe_label}]({url})" if url else safe_label


def format_annotation(decision: Decision) -> str:
    detail = f"{decision.job.name}: {decision.reason}"
    return f"::notice title=CI flake overseer: {decision.action}::{escape_annotation(detail)}"


def write_summary(path: Path | None, workflow_run: WorkflowRun, decisions: tuple[Decision, ...]) -> None:
    if path is None:
        return
    lines = [
        "### CI flake overseer (observe-only)",
        "",
        f"- Run: {markdown_link(workflow_run.name or str(workflow_run.id), workflow_run.html_url)}",
        f"- Head SHA: `{workflow_run.head_sha}`",
        f"- Attempt: `{workflow_run.run_attempt}`",
        "",
        "| Job | Decision | Reason |",
        "| --- | --- | --- |",
    ]
    for decision in decisions:
        lines.append(
            f"| {markdown_link(decision.job.name, decision.job.html_url)} | "
            f"`{decision.action}` | {escape_table(decision.reason)} |"
        )
    if not decisions:
        lines.append("| No failed jobs | `skip non-test` | workflow has no failed jobs to inspect |")
    with path.open("a") as summary:
        summary.write("\n".join(lines))
        summary.write("\n")


def parse_workflows(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_ALLOWED_WORKFLOWS
    workflows = tuple(item.strip() for item in value.split(",") if item.strip())
    return workflows or DEFAULT_ALLOWED_WORKFLOWS


def resolve_workflow_run(args: argparse.Namespace) -> WorkflowRun:
    if args.event_path:
        from_event = workflow_run_from_event(Path(args.event_path))
        if from_event is not None and (args.run_id is None or from_event.id == args.run_id):
            return from_event
    if args.run_id is None:
        raise ValueError("--run-id is required when the event payload does not contain workflow_run")
    return workflow_run_from_object(gh_json(args.repo, f"actions/runs/{args.run_id}"))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Observe failed CI test jobs and record what reruns do.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "PostHog/posthog"))
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument(
        "--enabled", action="store_true", default=as_bool_string(os.environ.get("CI_FLAKE_OVERSEER_ENABLED", ""))
    )
    parser.add_argument("--allowed-workflows", default=os.environ.get("CI_FLAKE_OVERSEER_WORKFLOWS"))
    parser.add_argument("--summary-path", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    # Reuses the DevEx project token already wired into other CI workflows; telemetry no-ops when absent.
    parser.add_argument("--posthog-api-key", default=os.environ.get("POSTHOG_DEVEX_PROJECT_API_TOKEN", ""))
    parser.add_argument("--posthog-host", default=os.environ.get("POSTHOG_DEVEX_PROJECT_HOST") or DEFAULT_POSTHOG_HOST)
    parser.add_argument("--posthog-timeout-seconds", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    summary_path = Path(args.summary_path) if args.summary_path else None
    try:
        workflow_run = resolve_workflow_run(args)
    except Exception as exc:
        print(f"::warning title=CI flake overseer failed closed::{escape_annotation(str(exc))}")
        return 0

    if workflow_run.name not in parse_workflows(args.allowed_workflows):
        print(f"::notice title=CI flake overseer skipped::Workflow `{workflow_run.name}` is not allowlisted")
        return 0
    if not args.enabled:
        print("::notice title=CI flake overseer disabled::Set CI_FLAKE_OVERSEER_ENABLED=true to record observations")
        return 0

    # On a re-run attempt, record whether the prior attempt's test failures cleared on rerun.
    events = report_rerun_outcomes(args.repo, workflow_run)

    if workflow_run.conclusion in {"failure", "timed_out"}:
        decisions = classify_failed_jobs(args.repo, workflow_run.id, workflow_run.run_attempt)
        for decision in decisions:
            print(format_annotation(decision))
        write_summary(summary_path, workflow_run, decisions)
        events.extend(build_decision_events(args.repo, workflow_run, decisions))
    else:
        print(f"::notice title=CI flake overseer skipped::Workflow conclusion is `{workflow_run.conclusion}`")

    capture_events(args.posthog_api_key, args.posthog_host, events, args.posthog_timeout_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
