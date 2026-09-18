#!/usr/bin/env python3
"""Send the running time of a Depot CI workflow run to PostHog, in the shape GitHub Actions sends it.

On GitHub Actions, PostHog/posthog-github-action reads the run and its jobs from the Actions API
and captures `posthog-ci-running-time` once per run and `posthog-ci-running-time-job` once per job.
A Depot CI run carries a GITHUB_RUN_ID that the Actions API does not know, so that action fails
there before it captures anything. This script reads the check runs that Depot CI posts for each
job instead, and sends the same properties plus `ci_engine` and `depot_workflow_id`, so a
consumer can tell the engines apart. It never fails the job that runs it.
"""

import os
import re
import sys
import json
import math
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

API_ROOT = "https://api.github.com"
# Depot Code Access, the GitHub App that posts one check run per Depot CI job.
DEPOT_CI_APP_ID = 219785
POSTHOG_HOST = "https://us.i.posthog.com"
EVENT = "posthog-ci-running-time"
# Kept equal to posthog-github-action's, so both engines' events share one person.
DISTINCT_ID = "posthog-github-action"
CI_ENGINE = "depot"
# The check-run details URL: https://depot.dev/orgs/<org>/workflows/<workflow id>?job=<job id>&...
WORKFLOW_URL = re.compile(r"^(https://depot\.dev/orgs/[^/?#]+/workflows/([^/?#]+))")
# Depot posts a job's check run once the job starts, so this job's own run can lag its first read.
LOOKUP_ATTEMPTS = 3
LOOKUP_BACKOFF_SECONDS = 10
PAGE_SIZE = 100


def warn(message: str) -> None:
    sys.stdout.write(f"::warning::{message}\n")


def classify_actor(actor: str) -> str:
    if not actor:
        return "unknown"
    return "bot" if actor.endswith("[bot]") or actor == "Copilot" else "human"


def as_int(value: str) -> int | None:
    return int(value) if value.isdecimal() else None


def github_context(env: dict[str, str]) -> dict[str, Any]:
    """The properties posthog-github-action adds to every event, read from the same variables."""
    owner, _, repository = env.get("GITHUB_REPOSITORY", "").partition("/")
    actor = env.get("GITHUB_ACTOR", "")
    return {
        "sha": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
        "workflow": env.get("GITHUB_WORKFLOW", ""),
        "runNumber": as_int(env.get("GITHUB_RUN_NUMBER", "")),
        "runId": as_int(env.get("GITHUB_RUN_ID", "")),
        "repository": repository,
        "repositoryOwner": owner,
        "actor": actor,
        "actor_type": classify_actor(actor),
        "eventName": env.get("GITHUB_EVENT_NAME", ""),
    }


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def workflow_of(check_run: dict[str, Any]) -> tuple[str, str] | None:
    """(workflow id, workflow URL) from a Depot check run's details URL."""
    match = WORKFLOW_URL.match(check_run.get("details_url") or "")
    return (match.group(2), match.group(1)) if match else None


def job_name(check_run: dict[str, Any]) -> str:
    """The job's display name. Depot names each check run `<workflow name> / <job name>`."""
    return str(check_run.get("name", "")).partition(" / ")[2]


def build_events(
    check_runs: list[dict[str, Any]],
    own_job: str,
    context: dict[str, Any],
    conclusion: str,
    attempt: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """The events for the workflow whose `own_job` check run is still in progress, or none when
    that workflow cannot be told apart from the others on the same commit."""
    own = {
        workflow
        for run in check_runs
        if run.get("status") == "in_progress" and job_name(run) == own_job and (workflow := workflow_of(run))
    }
    if len(own) != 1:
        return []
    workflow_id, url = own.pop()
    runs = [
        run
        for run in check_runs
        if (workflow := workflow_of(run)) and workflow[0] == workflow_id and run.get("started_at")
    ]
    started_at = min((run["started_at"] for run in runs), key=parse_time)
    group_key = f"{context['repositoryOwner']}/{context['repository']}/{context['runId']}"
    common = {
        "ci_engine": CI_ENGINE,
        "depot_workflow_id": workflow_id,
        **context,
        "$groups": {"workflow_run": group_key},
    }
    timestamp = now.isoformat()

    def event(name: str, properties: dict[str, Any]) -> dict[str, Any]:
        return {"event": name, "distinct_id": DISTINCT_ID, "timestamp": timestamp, "properties": properties}

    events = [
        event(
            EVENT,
            {
                "duration_seconds": math.floor((now - parse_time(started_at)).total_seconds()),
                "url": url,
                "attempt": attempt,
                "started_at": started_at,
                "conclusion": conclusion,
                "runner": "depot",
                **common,
            },
        )
    ]
    if conclusion:
        events.append(
            {
                "event": "$groupidentify",
                "distinct_id": f"$workflow_run_{group_key}",
                "timestamp": timestamp,
                "properties": {
                    "$group_type": "workflow_run",
                    "$group_key": group_key,
                    "$group_set": {"conclusion": conclusion},
                },
            }
        )
    # A retried job keeps its earlier check runs; the Actions API reports only a job's latest attempt.
    latest: dict[str, dict[str, Any]] = {}
    for run in sorted(runs, key=lambda run: run["id"]):
        latest[job_name(run)] = run
    for name, run in latest.items():
        if not run.get("completed_at") or name == own_job:
            continue
        duration = parse_time(run["completed_at"]) - parse_time(run["started_at"])
        events.append(
            event(
                f"{EVENT}-job",
                {
                    "name": name,
                    # Depot can stamp a skipped job's completed_at a second before its started_at.
                    "duration_seconds": max(0, math.floor(duration.total_seconds())),
                    "conclusion": run.get("conclusion"),
                    "started_at": run["started_at"],
                    "completed_at": run["completed_at"],
                    **common,
                },
            )
        )
    return events


def fetch_check_runs(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
    check_runs: list[dict[str, Any]] = []
    for page in range(1, 11):
        query = urllib.parse.urlencode(
            {"app_id": DEPOT_CI_APP_ID, "filter": "all", "per_page": PAGE_SIZE, "page": page}
        )
        request = urllib.request.Request(
            f"{API_ROOT}/repos/{repo}/commits/{sha}/check-runs?{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.loads(response.read().decode("utf-8"))["check_runs"]
        check_runs.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return check_runs


def capture(token: str, events: list[dict[str, Any]]) -> None:
    request = urllib.request.Request(
        f"{POSTHOG_HOST}/batch/",
        data=json.dumps({"api_key": token, "batch": events}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def main() -> int:
    env = dict(os.environ)
    tokens = {token for token in (env.get("POSTHOG_API_TOKEN"), env.get("POSTHOG_DEVEX_PROJECT_API_TOKEN")) if token}
    if not tokens:
        warn("No PostHog token is set, so no running time is sent.")
        return 0
    events: list[dict[str, Any]] = []
    for attempt in range(1, LOOKUP_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(LOOKUP_BACKOFF_SECONDS * (attempt - 1))
        try:
            check_runs = fetch_check_runs(
                env.get("GITHUB_REPOSITORY", ""), env.get("HEAD_SHA", ""), env.get("GH_TOKEN", "")
            )
        except (OSError, http.client.HTTPException, ValueError, KeyError) as error:
            warn(f"Cannot read the Depot CI check runs: {error}")
            # A 4xx fails the same way again and spends more of the installation token's shared rate limit.
            if isinstance(error, urllib.error.HTTPError) and error.code < 500:
                return 0
            continue
        events = build_events(
            check_runs,
            env.get("OWN_JOB_NAME", ""),
            github_context(env),
            env.get("CONCLUSION", ""),
            as_int(env.get("GITHUB_RUN_ATTEMPT", "")) or 1,
            datetime.now(UTC),
        )
        if events:
            break
    if not events:
        warn("Cannot find this job's check run, so the Depot CI workflow is unknown and no running time is sent.")
        return 0
    sent = 0
    for token in tokens:
        # One project's ingest failing must not block the other's.
        try:
            capture(token, events)
            sent += 1
        except (OSError, http.client.HTTPException) as error:
            warn(f"Cannot send the running time to PostHog: {error}")
    sys.stdout.write(f"Sent {len(events)} events to {sent} of {len(tokens)} PostHog project(s).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
