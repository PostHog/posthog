#!/usr/bin/env python3
"""
Track GitHub Actions job / step-level telemetry to PostHog.

Fixes vs. previous version
--------------------------
1. Correct PR number (`ci_pr_number`) instead of literal “merge”.
2. Adds PR title (`ci_pr_title`).
3. Includes explicit step duration (`ci_duration_seconds`) **and**
   a boolean flag for failure (`ci_failed`).
4. Adds a deep-link to the job/step in the GitHub UI (`ci_step_url`).
"""

import os
from datetime import datetime, UTC
from typing import Any, Optional

import requests

# --------------------------------------------------------------------------- #
#  Environment
# --------------------------------------------------------------------------- #

POSTHOG_API_KEY = os.environ["POSTHOG_API_KEY"]
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://app.posthog.com")
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
RUN_ID = os.environ["GITHUB_RUN_ID"]
REPOSITORY = os.environ["GITHUB_REPOSITORY"]
ACTOR = os.environ["GITHUB_ACTOR"]
WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "")
RUN_NUMBER = os.environ.get("GITHUB_RUN_NUMBER", "")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "")

owner, repo = REPOSITORY.split("/")

# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "posthog-ci-analytics",
}


def iso_to_dt(ts: Optional[str]) -> Optional[datetime]:
    """Convert ISO timestamp to aware datetime."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def pr_info() -> (Optional[str], Optional[str]):
    """
    Extract PR number & title.

    On `pull_request` events the ref looks like:
    `refs/pull/<number>/merge`
    """
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/pull/"):
        return None, None

    parts = ref.split("/")
    pr_number = parts[2] if len(parts) >= 3 else None
    title = None

    if pr_number:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=HEADERS,
            timeout=30,
        )
        if r.ok:
            title = r.json().get("title")

    return pr_number, title


def list_jobs() -> list[dict[str, Any]]:
    """Fetch **all** jobs (with pagination) for this run."""
    jobs: list[dict[str, Any]] = []
    page = 1
    while True:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{RUN_ID}/jobs",
            headers=HEADERS,
            timeout=30,
            params={"per_page": 100, "page": page},
        )
        r.raise_for_status()
        batch = r.json().get("jobs", [])
        if not batch:
            break
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #


def build_events(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transform the GitHub data into PostHog `batch` format."""
    pr_number, pr_title = pr_info()

    events = []
    for job in jobs:
        job_url = job.get("html_url")
        for idx, step in enumerate(job.get("steps", []), start=1):
            started = iso_to_dt(step.get("started_at"))
            completed = iso_to_dt(step.get("completed_at"))

            duration: Optional[float] = None
            if started and completed:
                duration = (completed - started).total_seconds()

            # Build a best-effort deep link to the *step* in the UI.
            # GitHub doesn’t expose a step url directly; the anchor format
            # is stable enough for first-party usage:
            #   <job html_url>#step:<1-based index>:<lower-kebab-name>
            step_anchor = step.get("name", "").lower().replace(" ", "-")
            step_url = f"{job_url}#step:{idx}:{step_anchor}" if job_url else None

            events.append(
                {
                    "event": "github action step",
                    "properties": {
                        "ci_workflow": WORKFLOW,
                        "ci_job": job.get("name"),
                        "ci_step": step.get("name"),
                        "ci_conclusion": step.get("conclusion"),
                        "ci_failed": step.get("conclusion") not in {"success", None},
                        "ci_duration_seconds": duration,
                        "ci_step_url": step_url,
                        "ci_run_id": RUN_ID,
                        "ci_run_number": RUN_NUMBER,
                        "ci_run_attempt": RUN_ATTEMPT,
                        "ci_pr_number": pr_number,
                        "ci_pr_title": pr_title,
                        "ci_sha": os.environ.get("GITHUB_SHA"),
                    },
                    "distinct_id": ACTOR,
                    # Use `completed_at` when available, else `started_at`, else NOW.
                    "timestamp": (
                        (step.get("completed_at") or step.get("started_at")) or datetime.now(UTC).isoformat()
                    ),
                }
            )
    return events


def main() -> None:
    jobs = list_jobs()
    if not jobs:
        print("No jobs found")  # noqa: T201
        return

    events = build_events(jobs)
    if not events:
        print("No step events generated")  # noqa: T201
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
    print(f"Sent {len(events)} step events to PostHog")  # noqa: T201


if __name__ == "__main__":
    main()
