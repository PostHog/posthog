#!/usr/bin/env python3
# ruff: noqa: T201 - CLI output is the contract for this script.

"""Triage a failed CI run into flake-vs-real and render a PR comment.

The companion to ``ci_flake_overseer.py``: the overseer *observes* (emits
telemetry, never touches the PR); this *acts* — it turns the same per-job
classification into a verdict a human can act on, and writes a comment body the
workflow upserts onto the PR. The goal is to delete the "is this red check mine
or just flaky?" decision the author otherwise makes by hand (and the
copy-paste-the-log-into-an-agent loop that follows it).

It reuses the overseer's classifier wholesale — deterministic vs test-runner vs
non-test — so the two stay in lockstep, and layers three signals on top:

  * a cleared-on-rerun check (a test that failed an earlier attempt and passed
    on rerun is a *proven* flake),
  * flake *history* via the CI-insights backend (``hogli ci:insights``/Mendral):
    a test matching a tracked, high-confidence flaky insight is upgraded to a
    "known flake" — see ``HogliInsightsHistory``, and
  * a verdict + rendered Markdown grouping failures into "rerun should clear
    these" vs "a rerun won't help — fix the code".

The history backend is best-effort: when it is absent, unauthed, or errors, the
verdict is unchanged, so the bot stays useful on the GitHub-only signals
(deterministic-vs-test and cleared-on-rerun) alone.

    python .github/scripts/ci_flake_triage.py --output comment.md
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import argparse
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

# Same-directory import: when run as `python .github/scripts/ci_flake_triage.py`
# the script's own dir is sys.path[0], and the unit tests add it the same way
# the overseer's tests do.
from ci_flake_overseer import (
    Decision,
    ExternalCommandError,
    Job,
    WorkflowRun,
    as_int,
    as_object,
    as_object_list,
    as_str,
    classify_job,
    escape_annotation,
    escape_table,
    fetch_jobs,
    index_unique_jobs_by_name,
    job_was_reexecuted,
    markdown_link,
    resolve_workflow_run,
    run_command,
)

COMMENT_MARKER = "<!-- ci-flake-triage -->"


def gh_text(repo: str, path: str) -> str:
    """Raw text from the GitHub API (job logs aren't JSON). Best-effort caller-side."""
    return run_command(("gh", "api", f"repos/{repo}/{path}", "--method", "GET"), timeout_seconds=90)


# Rollup "gate" jobs that fail only because a matrix shard below them failed
# (e.g. "Django Tests Pass" → "Check dependency results"). They echo the real
# failure rather than being it, so listing them just duplicates the comment.
# Drop them and point the author at the shard that actually went red.
_AGGREGATOR_JOB = re.compile(r"\b(tests? pass|checks?)\b$", re.IGNORECASE)
_AGGREGATOR_STEP = re.compile(r"\bcheck (dependency results|outcomes|.*\bstatus\b)", re.IGNORECASE)


def is_aggregator_rollup(job: Job) -> bool:
    if _AGGREGATOR_JOB.search(job.name.strip()):
        return True
    return any(_AGGREGATOR_STEP.search(step) for step in job.failed_step_names())


class Verdict(Enum):
    # A rerun cannot fix these — lint, types, migrations, OpenAPI, snapshots.
    REAL_DETERMINISTIC = "real_deterministic"
    # Build/setup/infra step that isn't a test runner — usually not flaky, but a
    # rerun occasionally clears genuine infra blips, so it's its own bucket.
    INFRA_NON_TEST = "infra_non_test"
    # A test job that failed an earlier attempt and passed on rerun: proven flake.
    FLAKE_PROVEN = "flake_proven"
    # A test failure matching a tracked, high-confidence flaky insight (Mendral).
    FLAKE_KNOWN = "flake_known"
    # A test job failure on the latest attempt, not yet reproven — rerunning a
    # test runner is what clears the common flakes, so lead the author there.
    TEST_UNRESOLVED = "test_unresolved"


# Author-facing copy per verdict: (whether a rerun is the right move, one-liner).
# FLAKE_KNOWN's detail is filled in dynamically with the matched insight, so its
# entry here is only a fallback.
_VERDICT_COPY: dict[Verdict, tuple[bool, str]] = {
    Verdict.REAL_DETERMINISTIC: (False, "deterministic check — a rerun won't help"),
    Verdict.INFRA_NON_TEST: (False, "build/setup failure — check the step log, not your tests"),
    Verdict.FLAKE_PROVEN: (True, "confirmed flake: failed an earlier attempt, passed on rerun"),
    Verdict.FLAKE_KNOWN: (True, "known flaky test — matches a tracked flake insight"),
    Verdict.TEST_UNRESOLVED: (True, "test-runner failure — these usually clear on rerun"),
}

# Test-runner verdicts eligible for flake-history enrichment. Deterministic and
# infra failures are never consulted — a rerun can't fix them regardless.
_TEST_VERDICTS = {Verdict.TEST_UNRESOLVED, Verdict.FLAKE_PROVEN}


@dataclass(frozen=True)
class TriagedJob:
    job: Job
    verdict: Verdict
    detail: str

    @property
    def rerun_clears(self) -> bool:
        return _VERDICT_COPY[self.verdict][0]


# --- Flake history (optional, best-effort) -----------------------------------
# Faithful port of the Mendral integration the overseer carried before it went
# observe-only (git 0b3fe26). It asks the CI-insights backend — `hogli ci:insights`,
# which wraps Mendral — whether a failing test matches a *tracked, high-confidence
# flaky* signature, so a 🟡 verdict can be upgraded from "test failures usually
# clear on rerun" to "known flaky test, here's the insight". An absent, unauthed,
# or erroring backend yields no match and leaves the verdict unchanged: the bot
# must stay useful on GitHub-only signals.

ACTIVE_INSIGHT_STATUSES = {"proposed", "in_progress", "in_review"}
DEFAULT_CONFIDENCE_THRESHOLD = 80
MAX_QUERY_COUNT = 8
MAX_INSIGHTS_PER_QUERY = 3
_FLAKY_KEYWORD = re.compile(r"\bflak(?:y|e|iness)\b|\bintermittent(?:ly)?\b", re.IGNORECASE)

# Signatures pulled from a failing job log, used as insight-search queries.
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


@dataclass(frozen=True)
class FlakeMatch:
    insight_id: str
    title: str
    confidence: int


class FlakeHistory(Protocol):
    def lookup(self, queries: tuple[str, ...], workflow_name: str, log: str) -> FlakeMatch | None: ...


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


def insight_text(insight: dict[str, object]) -> str:
    parts = [
        as_str(insight.get("title")) or "",
        as_str(insight.get("summary")) or "",
        as_str(insight.get("hypothesis_content")) or "",
    ]
    parts.extend(as_str(finding.get("content")) or "" for finding in as_object_list(insight.get("findings")))
    return "\n".join(parts)


def default_insights_command() -> tuple[str, ...]:
    local_hogli = Path("./bin/hogli")
    executable = str(local_hogli) if local_hogli.exists() else "hogli"
    return (executable, "ci:insights")


class HogliInsightsHistory:
    """Asks `hogli ci:insights` (Mendral) whether a failure is a tracked flake."""

    def __init__(self, command: tuple[str, ...], confidence_threshold: int, timeout_seconds: int = 20) -> None:
        self.command = command
        self.confidence_threshold = confidence_threshold
        self.timeout_seconds = timeout_seconds

    def lookup(self, queries: tuple[str, ...], workflow_name: str, log: str) -> FlakeMatch | None:
        for query in queries:
            for insight in self._search(query)[:MAX_INSIGHTS_PER_QUERY]:
                insight_id = as_str(insight.get("id"))
                if not insight_id:
                    continue
                detail = self._view(insight_id)  # the search payload omits confidence/status
                if detail and (match := self._flake_match(detail, query, workflow_name, log)) is not None:
                    return match
        return None

    def _search(self, query: str) -> list[dict[str, object]]:
        return as_object_list(json.loads(run_command((*self.command, "search", query, "--json"), self.timeout_seconds)))

    def _view(self, insight_id: str) -> dict[str, object]:
        parsed = json.loads(run_command((*self.command, "view", insight_id, "--json"), self.timeout_seconds))
        return parsed if isinstance(parsed, dict) else {}

    def _flake_match(self, insight: dict[str, object], query: str, workflow_name: str, log: str) -> FlakeMatch | None:
        confidence = as_int(insight.get("hypothesis_confidence")) or 0
        if confidence < self.confidence_threshold:
            return None
        if (as_str(insight.get("status")) or "").lower() not in ACTIVE_INSIGHT_STATUSES:
            return None
        insight_workflow = as_str(as_object(insight.get("source_ref")).get("workflow_name"))
        if insight_workflow and insight_workflow != workflow_name:
            return None
        text = insight_text(insight)
        if _FLAKY_KEYWORD.search(text) is None:
            return None
        # Require a concrete signature shared by the failure log and the insight, not just the
        # flakiness keyword — else an unrelated flaky insight would greenlight a rerun.
        text_lower, log_lower = text.lower(), log.lower()
        terms = significant_query_terms(query)
        if not any(term.lower() in text_lower and term.lower() in log_lower for term in terms):
            return None
        return FlakeMatch(
            insight_id=as_str(insight.get("id")) or "ci-insight",
            title=as_str(insight.get("title")) or "CI insight",
            confidence=confidence,
        )


def insights_history_if_available() -> HogliInsightsHistory | None:
    """The flake-history provider, or None when its backend isn't installed.

    Skipping when the executable is absent avoids one failed subprocess per query
    in the common CI case where Mendral/hogli isn't on the runner.
    """
    command = default_insights_command()
    if shutil.which(command[0]) is None and not Path(command[0]).exists():
        return None
    return HogliInsightsHistory(command, DEFAULT_CONFIDENCE_THRESHOLD)


def lookup_flake_history(
    history: FlakeHistory, job: Job, workflow_name: str, log_for: Callable[[Job], str]
) -> FlakeMatch | None:
    """Best-effort flake-history lookup for one job. Any backend hiccup -> None."""
    try:
        log = log_for(job)
        queries = extract_failure_queries(log)
        if not queries:
            return None
        return history.lookup(queries, workflow_name, log)
    except (ExternalCommandError, json.JSONDecodeError, ValueError):
        return None


def verdict_for(decision: Decision, *, cleared_on_rerun: bool) -> Verdict:
    if decision.action == "skip deterministic":
        return Verdict.REAL_DETERMINISTIC
    if decision.action == "skip non-test":
        return Verdict.INFRA_NON_TEST
    # decision.action == "observe" — a test-runner failure.
    return Verdict.FLAKE_PROVEN if cleared_on_rerun else Verdict.TEST_UNRESOLVED


def triage_jobs(
    jobs: tuple[Job, ...],
    cleared_job_names: frozenset[str],
    *,
    workflow_name: str = "",
    history: FlakeHistory | None = None,
    log_for: Callable[[Job], str] | None = None,
) -> list[TriagedJob]:
    triaged: list[TriagedJob] = []
    for job in jobs:
        if job.conclusion not in {"failure", "timed_out"}:
            continue
        if is_aggregator_rollup(job):
            continue
        verdict = verdict_for(classify_job(job), cleared_on_rerun=job.name in cleared_job_names)
        detail = _VERDICT_COPY[verdict][1]
        # Enrich a test-runner failure with flake history (Mendral) when available.
        if verdict in _TEST_VERDICTS and history is not None and log_for is not None:
            match = lookup_flake_history(history, job, workflow_name, log_for)
            if match is not None:
                verdict = Verdict.FLAKE_KNOWN
                pct = f" ({match.confidence}% confidence)" if match.confidence else ""
                detail = f"known flaky test{pct} — matches tracked insight `{match.insight_id}`; safe to rerun"
        triaged.append(TriagedJob(job=job, verdict=verdict, detail=detail))
    return triaged


def cleared_job_names(repo: str, workflow_run: WorkflowRun) -> frozenset[str]:
    """Test jobs that failed the prior attempt and were re-executed and passed.

    Mirrors ``ci_flake_overseer.report_rerun_outcomes`` — same strict prior-attempt
    fetch and started_at re-execution check — but returns names instead of events.
    """
    if workflow_run.run_attempt <= 1:
        return frozenset()
    prior = index_unique_jobs_by_name(fetch_jobs(repo, workflow_run.id, workflow_run.run_attempt - 1, strict=True))
    current = index_unique_jobs_by_name(fetch_jobs(repo, workflow_run.id, workflow_run.run_attempt))
    cleared: set[str] = set()
    for name, prior_job in prior.items():
        if prior_job.conclusion not in {"failure", "timed_out"}:
            continue
        if classify_job(prior_job).action != "observe":
            continue
        current_job = current.get(name)
        if current_job is None:
            continue
        if job_was_reexecuted(prior_job, current_job) and current_job.conclusion == "success":
            cleared.add(name)
    return frozenset(cleared)


def _bullet(item: TriagedJob) -> str:
    link = markdown_link(item.job.name, item.job.html_url)
    steps = item.job.failed_step_names()
    step_note = f" — failed step `{escape_table(steps[0])}`" if steps else ""
    return f"- {link}{step_note}\n  _{escape_table(item.detail)}_"


def render_comment(workflow_run: WorkflowRun, triaged: list[TriagedJob]) -> str | None:
    """Markdown comment body, or None when there is nothing actionable to say.

    Returning None lets the workflow leave (or clean up) the comment rather than
    posting an empty one — e.g. a run that failed with no classifiable job.
    """
    if not triaged:
        return None
    rerun = [t for t in triaged if t.rerun_clears]
    real = [t for t in triaged if not t.rerun_clears]

    counts: list[str] = []
    if rerun:
        counts.append(f"**{len(rerun)} likely-flaky** (rerun should clear)")
    if real:
        counts.append(f"**{len(real)} real** (needs a fix)")

    lines = [
        COMMENT_MARKER,
        f"### 🔍 CI failure triage — {escape_table(workflow_run.name)}",
        "",
        " · ".join(counts),
    ]
    if rerun:
        lines += ["", "🟡 **Likely flaky — a rerun should clear these**", *[_bullet(t) for t in rerun]]
    if real:
        lines += ["", "🔴 **Real failures — a rerun won't help**", *[_bullet(t) for t in real]]

    action = _suggested_action(len(rerun), len(real))
    lines += ["", f"**Suggested action:** {action}"]
    lines += [
        "",
        "---",
        "_Auto-triaged from job & step patterns (shared with the CI flake overseer). "
        "Heuristic, not always right — if a 🔴 is actually flaky, "
        "[quarantine it](https://github.com/PostHog/posthog/blob/master/.test_quarantine.json) so it stops blocking._",
    ]
    return "\n".join(lines)


def _suggested_action(rerun_count: int, real_count: int) -> str:
    if real_count and rerun_count:
        return f"fix the {real_count} real failure{_s(real_count)}, then rerun — the {rerun_count} flaky job{_s(rerun_count)} should clear."
    if real_count:
        return (
            f"fix the {real_count} real failure{_s(real_count)} before re-pushing; rerunning alone won't make CI green."
        )
    return (
        f"rerun the {rerun_count} failed job{_s(rerun_count)} — no real failure detected, so this is most likely flaky."
    )


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triage a failed CI run into flake-vs-real and render a PR comment.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "PostHog/posthog"))
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--output", default=os.environ.get("FLAKE_TRIAGE_OUTPUT", "flake-triage-comment.md"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        workflow_run = resolve_workflow_run(args)
    except Exception as exc:  # fail open: a triage hiccup must never block a PR
        print(f"::warning title=CI flake triage failed closed::{escape_annotation(str(exc))}")
        return 0

    if workflow_run.conclusion not in {"failure", "timed_out"}:
        print(f"::notice title=CI flake triage skipped::Workflow conclusion is `{workflow_run.conclusion}`")
        return 0

    jobs = fetch_jobs(args.repo, workflow_run.id, workflow_run.run_attempt)
    triaged = triage_jobs(
        jobs,
        cleared_job_names(args.repo, workflow_run),
        workflow_name=workflow_run.name,
        history=insights_history_if_available(),
        log_for=lambda job: gh_text(args.repo, f"actions/jobs/{job.id}/logs"),
    )
    body = render_comment(workflow_run, triaged)

    output = Path(args.output)
    if body is None:
        # Signal "no comment" to the workflow by writing an empty file rather than
        # a stale verdict from a previous step.
        output.write_text("")
        print("::notice title=CI flake triage::No classifiable failed jobs; nothing to comment.")
        return 0

    output.write_text(body)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
