#!/usr/bin/env python3
"""
Track GitHub Actions telemetry (workflow → job → step) to PostHog.

Key design points
-----------------
* **No more duplicates** – a job-scoped invocation only reports *its own* job
  and finished steps; a workflow-scoped invocation sends exactly **one**
  summary event for the whole run.
* **Runs on green *and* red builds** – call the action with `if: always()`.
* **Granularity**
  * *Workflow* → event **“github action workflow”** (full run blob).
  * *Job*      → event **“github action job”**     (full job blob).
  * *Step*     → event **“github action step”**    (only the *step* blob).
* **Only finished work** – a step is emitted only when
  `status == "completed"` *and* `conclusion` is not `None`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Optional

import requests

# --------------------------------------------------------------------------- #
#  Environment
# --------------------------------------------------------------------------- #

POSTHOG_API_KEY: str = os.environ["POSTHOG_API_KEY"]
POSTHOG_HOST: str = os.environ.get("POSTHOG_HOST", "https://app.posthog.com").rstrip("/")
GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]

REPOSITORY: str = os.environ["GITHUB_REPOSITORY"]  # org/repo
RUN_ID: str = os.environ["GITHUB_RUN_ID"]  # numeric
RUN_NUMBER: str | None = os.environ.get("GITHUB_RUN_NUMBER")
RUN_ATTEMPT: str | None = os.environ.get("GITHUB_RUN_ATTEMPT")
WORKFLOW_NAME: str | None = os.environ.get("GITHUB_WORKFLOW")

# Scope selector – “workflow” or “job” (default).
SCOPE: str = os.environ.get("CI_ANALYTICS_SCOPE", "job").lower()

# Present only in job-scope invocations.
CURRENT_JOB_NAME: str | None = os.environ.get("GITHUB_JOB")

ACTOR: str = os.environ["GITHUB_ACTOR"]
GITHUB_SERVER_URL: str = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

owner, repo = REPOSITORY.split("/")
RUN_URL = f"{GITHUB_SERVER_URL}/{owner}/{repo}/actions/runs/{RUN_ID}"

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "posthog-ci-analytics",
}

ANALYTICS_STEP_NAME = "Report job & steps to PostHog"


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def iso_to_dt(ts: Optional[str]) -> Optional[datetime]:
    """Convert ISO-8601 timestamp to timezone-aware ``datetime``."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def pr_info() -> tuple[Optional[str], Optional[str]]:
    """Return (PR number, PR title) when this run is on a pull request."""
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/pull/"):
        return None, None

    pr_number = ref.split("/")[2]
    try:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=HEADERS,
            timeout=30,
        )
        if r.ok:
            return pr_number, r.json().get("title")
    except requests.RequestException:
        pass
    return pr_number, None


def gh_get(url: str, **kwargs) -> dict[str, Any]:
    """GitHub GET helper with sane defaults and error surfacing."""
    resp = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------- #
#  GitHub fetch helpers
# --------------------------------------------------------------------------- #
def fetch_run() -> dict[str, Any]:
    return gh_get(f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{RUN_ID}")


def fetch_jobs() -> list[dict[str, Any]]:
    """Return **all** jobs for this run (handles pagination)."""
    all_jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = gh_get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{RUN_ID}/jobs",
            params={"per_page": 100, "page": page},
        ).get("jobs", [])
        if not batch:
            break
        all_jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return all_jobs


def find_current_job(jobs: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for j in jobs:
        for s in j.get("steps", []):
            if s.get("name") == ANALYTICS_STEP_NAME and s.get("conclusion") is None:
                return j
    return None  # should never happen; prints warning and exits


# --------------------------------------------------------------------------- #
#  Event builders
# --------------------------------------------------------------------------- #
def common_properties() -> dict[str, Any]:
    """Fields shared by **all** event types."""
    pr_number, pr_title = pr_info()
    return {
        "ci_owner": owner,
        "ci_repo": repo,
        "ci_workflow": WORKFLOW_NAME,
        "ci_run_id": RUN_ID,
        "ci_run_number": RUN_NUMBER,
        "ci_run_attempt": RUN_ATTEMPT,
        "ci_run_url": RUN_URL,
        "ci_pr_number": pr_number,
        "ci_pr_title": pr_title,
        "ci_sha": os.environ.get("GITHUB_SHA"),
    }


def build_workflow_event(run_raw: dict[str, Any]) -> dict[str, Any]:
    props = {
        **common_properties(),
        "ci_conclusion": run_raw.get("conclusion"),
        "ci_failed": run_raw.get("conclusion") not in {"success", None},
        "ci_workflow_started_at": run_raw.get("run_started_at"),
        "ci_workflow_completed_at": run_raw.get("updated_at"),
        "ci_workflow_raw": run_raw,
    }
    ts = run_raw.get("updated_at") or run_raw.get("run_started_at") or datetime.now(UTC).isoformat()
    return {
        "event": "github action workflow",
        "distinct_id": ACTOR,
        "timestamp": ts,
        "properties": props,
    }


def build_job_event(job_raw: dict[str, Any]) -> dict[str, Any]:
    started, completed = job_raw.get("started_at"), job_raw.get("completed_at")
    duration: Optional[float] = None
    if started and completed:
        dt_start, dt_end = iso_to_dt(started), iso_to_dt(completed)
        if dt_start and dt_end:
            duration = (dt_end - dt_start).total_seconds()

    props = {
        **common_properties(),
        "ci_job_id": job_raw.get("id"),
        "ci_job": job_raw.get("name"),
        "ci_conclusion": job_raw.get("conclusion"),
        "ci_failed": job_raw.get("conclusion") not in {"success", None},
        "ci_duration_seconds": duration,
        "ci_job_started_at": started,
        "ci_job_completed_at": completed,
        "ci_job_url": job_raw.get("html_url"),
        "ci_job_raw": job_raw,
    }
    ts = completed or started or datetime.now(UTC).isoformat()
    return {
        "event": "github action job",
        "distinct_id": ACTOR,
        "timestamp": ts,
        "properties": props,
    }


def build_step_events(job_raw: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for idx, step in enumerate(job_raw.get("steps", []), start=1):
        if step.get("status") != "completed" or step.get("conclusion") is None:
            # Skip pending / cancelled / in_progress steps altogether.
            continue

        s_started, s_completed = step.get("started_at"), step.get("completed_at")
        duration: Optional[float] = None
        if s_started and s_completed:
            dt_s, dt_c = iso_to_dt(s_started), iso_to_dt(s_completed)
            if dt_s and dt_c:
                duration = (dt_c - dt_s).total_seconds()

        # GitHub does not expose a canonical link to a *step*.  Best-effort anchor:
        step_anchor = step.get("name", "").lower().replace(" ", "-")
        step_url = f'{job_raw.get("html_url")}#step:{idx}:{step_anchor}' if job_raw.get("html_url") else None

        props = {
            **common_properties(),
            "ci_job_id": job_raw.get("id"),
            "ci_job": job_raw.get("name"),
            "ci_step_number": idx,
            "ci_step": step.get("name"),
            "ci_conclusion": step.get("conclusion"),
            "ci_failed": step.get("conclusion") not in {"success", None},
            "ci_duration_seconds": duration,
            "ci_job_started_at": job_raw.get("started_at"),
            "ci_job_completed_at": job_raw.get("completed_at"),
            "ci_step_started_at": s_started,
            "ci_step_completed_at": s_completed,
            "ci_job_url": job_raw.get("html_url"),
            "ci_step_url": step_url,
            "ci_step_raw": step,  # *no* ci_job_raw here – keeps payload light
        }

        ts = s_completed or s_started or datetime.now(UTC).isoformat()
        events.append(
            {
                "event": "github action step",
                "distinct_id": ACTOR,
                "timestamp": ts,
                "properties": props,
            }
        )

    return events


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def send_to_posthog(events: list[dict[str, Any]]) -> None:
    if not events:
        print("Nothing to send.")  # noqa: T201
        return

    payload = {
        "api_key": POSTHOG_API_KEY,
        "batch": [
            {
                "event": e["event"],
                "properties": e["properties"],
                "distinct_id": e["distinct_id"],
                "timestamp": e["timestamp"],
            }
            for e in events
        ],
    }
    resp = requests.post(f"{POSTHOG_HOST}/batch/", json=payload, timeout=30)
    resp.raise_for_status()
    print(f"✅ Sent {len(events)} event(s) to PostHog.")  # noqa: T201


def main() -> None:
    if SCOPE == "workflow":
        run_raw = fetch_run()
        send_to_posthog([build_workflow_event(run_raw)])
        return

    # ---- job scope (default) ------------------------------------------------
    all_jobs = fetch_jobs()
    target_job = find_current_job(all_jobs)

    if not target_job:
        print(f"⚠️  Current job '{CURRENT_JOB_NAME}' not found in run {RUN_ID}.")  # noqa: T201
        return

    events = [build_job_event(target_job), *build_step_events(target_job)]
    send_to_posthog(events)


if __name__ == "__main__":
    main()
