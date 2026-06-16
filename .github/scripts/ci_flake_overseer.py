#!/usr/bin/env python3
# ruff: noqa: T201 - CLI output is the contract for this script.

from __future__ import annotations

import os
import re
import sys
import json
import shlex
import argparse
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

JsonObject = dict[str, object]
DecisionAction = Literal["rerun", "skip deterministic", "skip unknown", "skip cap reached"]

ACTIVE_INSIGHT_STATUSES = {"open", "in_progress"}
DEFAULT_ALLOWED_WORKFLOWS = ("Backend CI", "Dagster CI", "E2E CI Playwright")
MAX_QUERY_COUNT = 8
MAX_INSIGHTS_PER_QUERY = 3


def compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


DETERMINISTIC_JOB_PATTERNS = compile_patterns(
    r"\brepo checks?\b",
    r"\bopenapi\b",
    r"\bmigrations?\b",
    r"\blint\b",
    r"\btype ?check\b",
    r"\btypescript\b",
    r"\bvisual\b",
    r"\bsnapshot\b",
    r"\bstorybook\b",
    r"\btach\b",
    r"\bimport-linter\b",
)

DETERMINISTIC_STEP_PATTERNS = compile_patterns(
    r"\bcheck module boundaries\b",
    r"\bproduct facade enforcement\b",
    r"\bopenapi\b",
    r"\bmigrations?\b",
    r"\blint\b",
    r"\btype ?check\b",
    r"\btypescript\b",
    r"\bvisual review\b",
    r"\bsnapshot\b",
    r"\bverify changed playwright tests are stable\b",
    r"\bverify new snapshots\b",
)

DETERMINISTIC_LOG_PATTERNS = compile_patterns(
    r"Repo checks failed deterministically",
    r"OpenAPI (?:type )?checks? failed deterministically",
    r"A retry cannot fix this failure",
    r"tach check --dependencies --interfaces",
    r"\blint-imports\b",
    r"OpenAPI types are out of date",
    r"hogli build:openapi",
    r"makemigrations --check",
    r"Snapshot commit job failed",
    r"does not match (?:the )?snapshot",
    r"__diff_output__",
    r"Visual Review did not complete successfully",
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

# Case-sensitive: test identifiers and error codes are matched exactly as they appear in logs.
FAILURE_QUERY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"FAILED\s+([A-Za-z0-9_./:-]+(?:::[A-Za-z0-9_./:-]+)*(?:\[[^\]\n]+\])?)",
        r"([A-Za-z0-9_./-]+\.py::[A-Za-z0-9_:\[\]./-]+)",
        r"\b(test_[A-Za-z0-9_]+)\b",
        r"([A-Za-z0-9_./-]+\.spec\.tsx?:\d+:\d+\s+›\s+[^\n]+)",
        r"\[[^\]\n]+\]\s+›\s+([^\n]{10,180})",
        r"\b([A-Z][A-Z0-9_]{8,})\b",
    )
)


class ExternalCommandError(Exception):
    pass


class InsightsUnavailable(Exception):
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
    steps: tuple[Step, ...] = ()

    def failed_step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if step.conclusion in {"failure", "timed_out"})


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    workflow_id: int
    name: str
    conclusion: str | None
    event: str
    head_sha: str
    run_attempt: int
    html_url: str


@dataclass(frozen=True)
class FlakeMatch:
    insight_id: str
    title: str
    confidence: int
    source: str
    matched_query: str
    summary: str


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    reason: str
    job: Job
    match: FlakeMatch | None = None


class InsightsSource(Protocol):
    def find_flake(self, queries: tuple[str, ...], workflow_name: str, job_name: str, log: str) -> FlakeMatch | None:
        pass


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


def gh_text(repo: str, path: str) -> str:
    return run_command(("gh", "api", f"repos/{repo}/{path}", "--method", "GET"), timeout_seconds=90)


def gh_post(repo: str, path: str) -> None:
    run_command(("gh", "api", f"repos/{repo}/{path}", "--method", "POST", "--silent"), timeout_seconds=30)


class CiInsightsSource:
    def __init__(self, command: tuple[str, ...], confidence_threshold: int, timeout_seconds: int) -> None:
        self.command = command
        self.confidence_threshold = confidence_threshold
        self.timeout_seconds = timeout_seconds

    def find_flake(self, queries: tuple[str, ...], workflow_name: str, job_name: str, log: str) -> FlakeMatch | None:
        for query in queries:
            for insight in self.search(query)[:MAX_INSIGHTS_PER_QUERY]:
                insight_id = as_str(insight.get("id"))
                if not insight_id:
                    continue
                match = self.flake_match(self.view(insight_id) or insight, query, workflow_name, job_name, log)
                if match is not None:
                    return match
        return None

    def search(self, query: str) -> list[JsonObject]:
        raw = self.run((*self.command, "search", query, "--json"))
        parsed = json.loads(raw)
        return as_object_list(parsed)

    def view(self, insight_id: str) -> JsonObject:
        raw = self.run((*self.command, "view", insight_id, "--json"))
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}

    def run(self, args: tuple[str, ...]) -> str:
        try:
            return run_command(args, timeout_seconds=self.timeout_seconds)
        except ExternalCommandError as exc:
            raise InsightsUnavailable(str(exc)) from exc

    def flake_match(
        self,
        insight: JsonObject,
        query: str,
        workflow_name: str,
        job_name: str,
        log: str,
    ) -> FlakeMatch | None:
        confidence = as_int(insight.get("hypothesis_confidence")) or 0
        if confidence < self.confidence_threshold:
            return None
        status = (as_str(insight.get("status")) or "").lower()
        if status not in ACTIVE_INSIGHT_STATUSES:
            return None
        source_ref = as_object(insight.get("source_ref"))
        insight_workflow = as_str(source_ref.get("workflow_name"))
        if insight_workflow and insight_workflow != workflow_name:
            return None

        text = insight_text(insight)
        if re.search(r"\bflak(?:y|e|iness)\b|\bintermittent(?:ly)?\b", text, re.IGNORECASE) is None:
            return None
        terms = significant_query_terms(query)
        text_lower = text.lower()
        log_lower = log.lower()
        if terms and not any(term.lower() in text_lower and term.lower() in log_lower for term in terms):
            return None

        return FlakeMatch(
            insight_id=as_str(insight.get("id")) or "ci-insight",
            title=as_str(insight.get("title")) or "CI insight",
            confidence=confidence,
            source="ci:insights",
            matched_query=query,
            summary=as_str(insight.get("summary")) or "",
        )


def workflow_run_from_object(raw: JsonObject) -> WorkflowRun:
    return WorkflowRun(
        id=as_int(raw.get("id")) or 0,
        workflow_id=as_int(raw.get("workflow_id")) or 0,
        name=as_str(raw.get("name")) or as_str(raw.get("workflow_name")) or "",
        conclusion=as_str(raw.get("conclusion")),
        event=as_str(raw.get("event")) or "",
        head_sha=as_str(raw.get("head_sha")) or "",
        run_attempt=as_int(raw.get("run_attempt")) or 1,
        html_url=as_str(raw.get("html_url")) or "",
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
        run_attempt=run_attempt,
        html_url=as_str(raw.get("html_url")) or "",
        steps=tuple(
            Step(name=as_str(step.get("name")) or "", conclusion=as_str(step.get("conclusion")))
            for step in as_object_list(raw.get("steps"))
        ),
    )


def fetch_jobs(repo: str, run_id: int, run_attempt: int) -> tuple[Job, ...]:
    jobs: list[Job] = []
    page = 1
    while True:
        try:
            raw = gh_json(repo, f"actions/runs/{run_id}/attempts/{run_attempt}/jobs?per_page=100&page={page}")
        except ExternalCommandError:
            raw = gh_json(repo, f"actions/runs/{run_id}/jobs?per_page=100&page={page}")
        page_jobs = as_object_list(raw.get("jobs"))
        jobs.extend(job_from_object(job, run_attempt) for job in page_jobs)
        if len(page_jobs) < 100:
            return tuple(jobs)
        page += 1


def fetch_runs_for_head_sha(repo: str, workflow_id: int, head_sha: str) -> tuple[WorkflowRun, ...]:
    if workflow_id == 0 or not head_sha:
        return ()
    runs: list[WorkflowRun] = []
    page = 1
    while True:
        raw = gh_json(repo, f"actions/workflows/{workflow_id}/runs?head_sha={head_sha}&per_page=100&page={page}")
        page_runs = as_object_list(raw.get("workflow_runs"))
        runs.extend(workflow_run_from_object(run) for run in page_runs)
        if len(page_runs) < 100:
            return tuple(runs)
        page += 1


def prior_rerun_cap_reason(repo: str, workflow_run: WorkflowRun, job: Job, max_reruns_per_job: int) -> str | None:
    try:
        prior_runs = fetch_runs_for_head_sha(repo, workflow_run.workflow_id, workflow_run.head_sha)
    except ExternalCommandError:
        return None
    for prior_run in prior_runs:
        if prior_run.id == workflow_run.id or prior_run.run_attempt <= max_reruns_per_job:
            continue
        try:
            prior_jobs = fetch_jobs(repo, prior_run.id, prior_run.run_attempt)
        except ExternalCommandError:
            continue
        if any(prior_job.name == job.name for prior_job in prior_jobs):
            return (
                f"matching job already reached attempt {prior_run.run_attempt} for head SHA "
                f"{workflow_run.head_sha} in run {prior_run.id}"
            )
    return None


def deterministic_reason(job: Job, log: str) -> str | None:
    for pattern in DETERMINISTIC_JOB_PATTERNS:
        if pattern.search(job.name):
            return f"job name matches deterministic rule `{pattern.pattern}`"
    for step_name in job.failed_step_names():
        for pattern in DETERMINISTIC_STEP_PATTERNS:
            if pattern.search(step_name):
                return f"failed step `{step_name}` matches deterministic rule `{pattern.pattern}`"
    for pattern in DETERMINISTIC_LOG_PATTERNS:
        if pattern.search(log):
            return f"log matches deterministic rule `{pattern.pattern}`"
    return None


def is_test_job_failure(job: Job) -> bool:
    failed_steps = job.failed_step_names()
    if failed_steps:
        return any(pattern.search(step_name) for step_name in failed_steps for pattern in TEST_STEP_PATTERNS)
    return any(pattern.search(job.name) for pattern in TEST_JOB_PATTERNS)


def extract_failure_queries(log: str) -> tuple[str, ...]:
    queries: list[str] = []
    for pattern in FAILURE_QUERY_PATTERNS:
        for match in pattern.finditer(log):
            query = " ".join(match.group(1).strip().split())
            if query and query not in queries:
                queries.append(query[:220])
            if len(queries) >= MAX_QUERY_COUNT:
                return tuple(queries)
    return tuple(queries)


def significant_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for pattern in (r"\b(test_[A-Za-z0-9_]+)\b", r"\b([A-Z][A-Z0-9_]{8,})\b"):
        terms.extend(match.group(1) for match in re.finditer(pattern, query))
    if not terms and len(query) >= 12:
        terms.append(query)
    return tuple(dict.fromkeys(terms))


def insight_text(insight: JsonObject) -> str:
    parts = [
        as_str(insight.get("title")) or "",
        as_str(insight.get("summary")) or "",
        as_str(insight.get("hypothesis_content")) or "",
    ]
    for finding in as_object_list(insight.get("findings")):
        parts.append(as_str(finding.get("content")) or "")
    return "\n".join(parts)


def classify_job(
    job: Job,
    log: str,
    insights: InsightsSource,
    workflow_name: str,
    max_reruns_per_job: int,
    get_cap_reached_reason: Callable[[], str | None] | None = None,
) -> Decision:
    deterministic = deterministic_reason(job, log)
    if deterministic is not None:
        return Decision(action="skip deterministic", reason=deterministic, job=job)
    # Gate on test-type before the rerun cap so a non-test job never reports "skip cap reached"
    # (which would imply raising the cap could help); the cap only ever applies to test jobs.
    if not is_test_job_failure(job):
        return Decision(action="skip unknown", reason="failed job or step is not an allowlisted test runner", job=job)
    if job.run_attempt > max_reruns_per_job:
        return Decision(
            action="skip cap reached",
            reason=f"run attempt {job.run_attempt} is above the automatic rerun cap {max_reruns_per_job}",
            job=job,
        )
    cap_reached_reason = get_cap_reached_reason() if get_cap_reached_reason is not None else None
    if cap_reached_reason is not None:
        return Decision(action="skip cap reached", reason=cap_reached_reason, job=job)

    queries = extract_failure_queries(log)
    if not queries:
        return Decision(action="skip unknown", reason="no failed test or error signature found in logs", job=job)
    try:
        match = insights.find_flake(queries, workflow_name, job.name, log)
    except InsightsUnavailable as exc:
        return Decision(action="skip unknown", reason=f"CI insights unavailable: {exc}", job=job)
    if match is None:
        return Decision(
            action="skip unknown",
            reason=f"no high-confidence known flaky signature matched: {', '.join(queries[:3])}",
            job=job,
        )
    return Decision(action="rerun", reason="matched high-confidence known flaky signature", job=job, match=match)


def inspect_failed_jobs(
    repo: str,
    workflow_run: WorkflowRun,
    insights: InsightsSource,
    max_reruns_per_job: int,
) -> tuple[Decision, ...]:
    decisions: list[Decision] = []
    for job in fetch_jobs(repo, workflow_run.id, workflow_run.run_attempt):
        if job.conclusion != "failure":
            continue
        try:
            log = gh_text(repo, f"actions/jobs/{job.id}/logs")
        except ExternalCommandError as exc:
            decisions.append(Decision(action="skip unknown", reason=f"could not fetch job log: {exc}", job=job))
            continue
        decisions.append(
            classify_job(
                job,
                log,
                insights,
                workflow_run.name,
                max_reruns_per_job,
                lambda job=job: prior_rerun_cap_reason(repo, workflow_run, job, max_reruns_per_job),
            )
        )
    return tuple(decisions)


def rerun_eligible_jobs(repo: str, decisions: tuple[Decision, ...], dry_run: bool) -> None:
    for decision in decisions:
        print(format_annotation(decision))
        if decision.action != "rerun":
            continue
        if dry_run:
            print(f"dry-run: would rerun job {decision.job.id} ({decision.job.name})")
            continue
        try:
            gh_post(repo, f"actions/jobs/{decision.job.id}/rerun")
            print(f"reran job {decision.job.id} ({decision.job.name})")
        except ExternalCommandError as exc:
            print(f"::warning title=CI flake overseer rerun failed::{escape_annotation(f'{decision.job.name}: {exc}')}")


def format_annotation(decision: Decision) -> str:
    title = f"CI flake overseer: {decision.action}"
    detail = f"{decision.job.name}: {decision.reason}"
    if decision.match is not None:
        detail = (
            f"{detail}; {decision.match.title} "
            f"({decision.match.insight_id}, confidence {decision.match.confidence}, matched `{decision.match.matched_query}`)"
        )
    return f"::notice title={title}::{escape_annotation(detail)}"


def escape_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def markdown_link(label: str, url: str) -> str:
    safe_label = escape_table(label)
    return f"[{safe_label}]({url})" if url else safe_label


def write_summary(
    path: Path | None,
    workflow_run: WorkflowRun,
    decisions: tuple[Decision, ...],
    dry_run: bool,
    max_reruns_per_job: int,
) -> None:
    if path is None:
        return
    lines = [
        "### CI flake overseer",
        "",
        f"- Run: {markdown_link(workflow_run.name or str(workflow_run.id), workflow_run.html_url)}",
        f"- Head SHA: `{workflow_run.head_sha}`",
        f"- Attempt: `{workflow_run.run_attempt}`",
        f"- Mode: `{'dry-run' if dry_run else 'active'}`",
        f"- Max automatic reruns per job/head SHA: `{max_reruns_per_job}`",
        "",
        "| Job | Decision | Reason | Matched flake |",
        "| --- | --- | --- | --- |",
    ]
    for decision in decisions:
        match = ""
        if decision.match is not None:
            match = (
                f"`{decision.match.insight_id}`: {decision.match.title} "
                f"(confidence {decision.match.confidence}, matched `{decision.match.matched_query}`)"
            )
        lines.append(
            "| "
            f"{markdown_link(decision.job.name, decision.job.html_url)} | "
            f"`{decision.action}` | "
            f"{escape_table(decision.reason)} | "
            f"{escape_table(match)} |"
        )
    if not decisions:
        lines.append("| No failed jobs | `skip unknown` | workflow has no failed jobs to inspect | |")
    with path.open("a") as summary:
        summary.write("\n".join(lines))
        summary.write("\n")


def default_insights_command() -> tuple[str, ...]:
    local_hogli = Path("./bin/hogli")
    executable = str(local_hogli) if local_hogli.exists() else "hogli"
    return (executable, "ci:insights")


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
    parser = argparse.ArgumentParser(description="Conservatively rerun CI jobs that match known flaky signatures.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "PostHog/posthog"))
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument(
        "--dry-run", action="store_true", default=as_bool_string(os.environ.get("CI_FLAKE_OVERSEER_DRY_RUN", ""))
    )
    parser.add_argument(
        "--enabled", action="store_true", default=as_bool_string(os.environ.get("CI_FLAKE_OVERSEER_ENABLED", ""))
    )
    parser.add_argument(
        "--max-reruns-per-job",
        type=int,
        default=int(os.environ.get("CI_FLAKE_OVERSEER_MAX_RERUNS", "1")),
    )
    parser.add_argument(
        "--confidence-threshold",
        type=int,
        default=int(os.environ.get("CI_FLAKE_OVERSEER_CONFIDENCE_THRESHOLD", "80")),
    )
    parser.add_argument("--insights-command", default=os.environ.get("CI_FLAKE_OVERSEER_HOGLI_COMMAND", ""))
    parser.add_argument("--insights-timeout-seconds", type=int, default=20)
    parser.add_argument("--allowed-workflows", default=os.environ.get("CI_FLAKE_OVERSEER_WORKFLOWS"))
    parser.add_argument("--summary-path", default=os.environ.get("GITHUB_STEP_SUMMARY"))
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
    if not args.enabled and not args.dry_run:
        print(
            "::notice title=CI flake overseer disabled::Set CI_FLAKE_OVERSEER_ENABLED=true to enable automatic reruns"
        )
        return 0
    if workflow_run.conclusion not in {"failure", "timed_out", "cancelled"}:
        print(f"::notice title=CI flake overseer skipped::Workflow conclusion is `{workflow_run.conclusion}`")
        return 0

    command = tuple(shlex.split(args.insights_command)) if args.insights_command else default_insights_command()
    insights = CiInsightsSource(command, args.confidence_threshold, args.insights_timeout_seconds)
    decisions = inspect_failed_jobs(args.repo, workflow_run, insights, args.max_reruns_per_job)
    dry_run = args.dry_run or not args.enabled
    rerun_eligible_jobs(args.repo, decisions, dry_run)
    write_summary(summary_path, workflow_run, decisions, dry_run, args.max_reruns_per_job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
