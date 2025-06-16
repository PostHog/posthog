#!/usr/bin/env python3
"""
Track GitHub Actions job / step‑level telemetry to PostHog, **richly**.

Changes in this version
-----------------------
1. **Deep‑links everywhere** – adds both job‑level and run‑level URLs
   (``ci_job_url`` & ``ci_run_url``).
2. **Raw timestamps** – ``ci_step_started_at`` / ``ci_step_completed_at`` and
   ``ci_job_started_at`` / ``ci_job_completed_at`` to avoid relying solely on a
   derived duration.
3. **Fallback duration** – if GitHub omits ``completed_at`` we still send
   ``ci_duration_seconds == None`` so that downstream queries can detect the
   gap.
4. **Complete context dumps** – marshal the original ``job`` and ``step`` JSON
   blobs into ``ci_job_raw`` and ``ci_step_raw`` in case you want *anything*
   that isn’t explicitly mapped.
5. **Extra identifiers** – run number/attempt, job id, step index, etc.

The goal is to provide PostHog with *all* the data we have, not to pick and
choose.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
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
GITHUB_SERVER_URL = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

owner, repo = REPOSITORY.split("/")
RUN_URL = f"{GITHUB_SERVER_URL}/{owner}/{repo}/actions/runs/{RUN_ID}"

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


def pr_info() -> tuple[Optional[str], Optional[str]]:
    """Extract PR number & title from ``GITHUB_REF`` when available."""
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/pull/"):
        return None, None

    pr_number = ref.split("/")[2]
    title: Optional[str] = None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=HEADERS,
            timeout=30,
        )
        if r.ok:
            title = r.json().get("title")
    except requests.RequestException:
        pass
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
    """Transform the GitHub data into PostHog ``batch`` format (max fidelity)."""
    pr_number, pr_title = pr_info()

    events: list[dict[str, Any]] = []
    for job in jobs:
        job_url: Optional[str] = job.get("html_url")
        job_started = job.get("started_at")
        job_completed = job.get("completed_at")

        for idx, step in enumerate(job.get("steps", []), start=1):
            # Raw timestamps as‑is.
            step_started_raw = step.get("started_at")
            step_completed_raw = step.get("completed_at")

            # Derived duration (may be None – we *preserve* that fact).
            duration: Optional[float] = None
            started_dt, completed_dt = iso_to_dt(step_started_raw), iso_to_dt(step_completed_raw)
            if started_dt and completed_dt:
                duration = (completed_dt - started_dt).total_seconds()

            # Best‑effort deep link to *step* (GitHub doesn’t publish one).
            step_anchor = step.get("name", "").lower().replace(" ", "-")
            step_url = f"{job_url}#step:{idx}:{step_anchor}" if job_url else None

            # Unified timestamp – prefer completed > started > now.
            firestore_ts = step_completed_raw or step_started_raw or datetime.now(UTC).isoformat()

            events.append(
                {
                    "event": "github action step",
                    "properties": {
                        # Workflow / run / job identifiers ---------------------------------
                        "ci_owner": owner,
                        "ci_repo": repo,
                        "ci_workflow": WORKFLOW,
                        "ci_run_id": RUN_ID,
                        "ci_run_number": RUN_NUMBER,
                        "ci_run_attempt": RUN_ATTEMPT,
                        "ci_job_id": job.get("id"),
                        "ci_job": job.get("name"),
                        "ci_step": step.get("name"),
                        "ci_step_number": idx,
                        # Conclusions & metrics --------------------------------------------
                        "ci_conclusion": step.get("conclusion"),
                        "ci_failed": step.get("conclusion") not in {"success", None},
                        "ci_duration_seconds": duration,
                        # URLs --------------------------------------------------------------
                        "ci_run_url": RUN_URL,
                        "ci_job_url": job_url,
                        "ci_step_url": step_url,
                        # Timestamps --------------------------------------------------------
                        "ci_job_started_at": job_started,
                        "ci_job_completed_at": job_completed,
                        "ci_step_started_at": step_started_raw,
                        "ci_step_completed_at": step_completed_raw,
                        # Pull Request context ---------------------------------------------
                        "ci_pr_number": pr_number,
                        "ci_pr_title": pr_title,
                        # Commit context ----------------------------------------------------
                        "ci_sha": os.environ.get("GITHUB_SHA"),
                        # Raw GitHub payloads -----------------------------------------------
                        "ci_job_raw": job,  # json object
                        "ci_step_raw": step,  # json object
                    },
                    "distinct_id": ACTOR,
                    "timestamp": firestore_ts,
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

    # Debugging aid – uncomment to inspect the JSON we send.
    # print(json.dumps(payload, indent=2))

    try:
        resp = requests.post(f"{POSTHOG_HOST.rstrip('/')}/batch/", json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as err:
        print("Failed to send telemetry to PostHog:", err)  # noqa: T201
        raise

    print(f"Sent {len(events)} GitHub Action step events to PostHog")  # noqa: T201


if __name__ == "__main__":
    main()
