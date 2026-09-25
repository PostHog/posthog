#!/usr/bin/env python3
"""Send the Backend CI running-time events for a Depot CI run.

On GitHub Actions, PostHog/posthog-github-action sends `posthog-ci-running-time` and one
`posthog-ci-running-time-job` event per job. It reads the run from the Actions API by run id,
and GitHub has no run for a Depot run id. This script reads the workflow with
`depot ci workflow show` instead and sends the same events with the same property keys.
`workflow` and `runner` tell the two engines apart.
"""

import os
import re
import sys
import json
import math
import datetime as dt
import subprocess
import urllib.request
from collections.abc import Mapping
from typing import Any

JSONObject = dict[str, Any]

POSTHOG_BATCH_URL = "https://us.i.posthog.com/batch/"
EVENT = "posthog-ci-running-time"
DISTINCT_ID = "posthog-github-action"
RUNNER = "depot-ci"
REQUEST_TIMEOUT_SECONDS = 30
DEPOT_JOB_URL = re.compile(r"^(https://depot\.dev/orgs/([^/?]+)/workflows/([a-z0-9]+))")
# Depot's terminal job statuses in GitHub's conclusion vocabulary. `cancelled` and `skipped` already match.
CONCLUSION_BY_STATUS = {"finished": "success", "failed": "failure"}
# Depot posts one placeholder job per matrix that it expands from `fromJSON`. The placeholder runs nothing.
MATRIX_PLACEHOLDER_SUFFIX = ":_dynamicMatrix"
KNOWN_BOT_ACTORS = frozenset({"Copilot"})


def conclusion(status: str) -> str:
    return CONCLUSION_BY_STATUS.get(status, status)


def actor_type(actor: str) -> str:
    if not actor:
        return "unknown"
    if actor.endswith("[bot]") or actor in KNOWN_BOT_ACTORS:
        return "bot"
    return "human"


def seconds_between(started_at: str, finished_at: str) -> int:
    elapsed = dt.datetime.fromisoformat(finished_at) - dt.datetime.fromisoformat(started_at)
    return math.floor(elapsed.total_seconds())


def github_context(env: Mapping[str, str]) -> JSONObject:
    owner, _, repository = env["GITHUB_REPOSITORY"].partition("/")
    actor = env.get("GITHUB_ACTOR", "")
    run_number = env.get("GITHUB_RUN_NUMBER", "")
    return {
        "sha": env["GITHUB_SHA"],
        "ref": env["GITHUB_REF"],
        "workflow": env["GITHUB_WORKFLOW"],
        "runNumber": int(run_number) if run_number.isdigit() else None,
        "runId": int(env["GITHUB_RUN_ID"]),
        "repository": repository,
        "repositoryOwner": owner,
        "actor": actor,
        "actor_type": actor_type(actor),
        "eventName": env["GITHUB_EVENT_NAME"],
    }


def job_events(jobs: list[JSONObject], context: JSONObject, groups: JSONObject) -> list[JSONObject]:
    events: list[JSONObject] = []
    for job in jobs:
        if job["job_key"].endswith(MATRIX_PLACEHOLDER_SUFFIX):
            continue
        # A retried job keeps its earlier attempts. The Actions API reports the latest attempt only.
        latest = max(job.get("attempts") or [job], key=lambda attempt: attempt.get("attempt", 0))
        finished_at = latest.get("finished_at")
        if not finished_at:
            continue
        # A skipped job never starts, and the Actions API reports it with a zero duration.
        started_at = latest.get("started_at") or finished_at
        events.append(
            {
                "event": f"{EVENT}-job",
                "properties": {
                    "name": job.get("job_display_name") or job["job_key"],
                    "duration_seconds": seconds_between(started_at, finished_at),
                    "conclusion": conclusion(job["status"]),
                    "started_at": started_at,
                    "completed_at": finished_at,
                    "runner": RUNNER,
                    **context,
                    "$groups": groups,
                },
            }
        )
    return events


def build_events(
    shown: JSONObject, workflow_url: str, status_job: str, env: Mapping[str, str], now: dt.datetime
) -> list[JSONObject]:
    context = github_context(env)
    group_key = f"{context['repositoryOwner']}/{context['repository']}/{context['runId']}"
    groups = {"workflow_run": group_key}
    started_at = shown["workflow"]["started_at"]
    properties: JSONObject = {
        "duration_seconds": seconds_between(started_at, now.isoformat()),
        "url": workflow_url,
        "attempt": int(env["GITHUB_RUN_ATTEMPT"]),
        "started_at": started_at,
        "runner": RUNNER,
    }
    jobs = shown.get("jobs") or []
    # A job key is `<workflow file>:<job id>`, with a `:matrix-NN` suffix on matrix cells.
    gate = next((job for job in jobs if job["job_key"].partition(":")[2] == status_job), None)
    if gate is None:
        sys.stdout.write(f"::warning::Job '{status_job}' not found in the Depot workflow\n")
    else:
        properties["conclusion"] = conclusion(gate["status"])

    events = [{"event": EVENT, "properties": {**properties, **context, "$groups": groups}}]
    if "conclusion" in properties:
        events.append(
            {
                "event": "$groupidentify",
                "properties": {
                    "$group_type": "workflow_run",
                    "$group_key": group_key,
                    "$group_set": {"conclusion": properties["conclusion"]},
                },
                "distinct_id": f"$workflow_run_{group_key}",
            }
        )
    events.extend(job_events(jobs, context, groups))
    timestamp = now.isoformat()
    return [{"distinct_id": DISTINCT_ID, "timestamp": timestamp, **event} for event in events]


def send_batch(token: str, events: list[JSONObject]) -> None:
    request = urllib.request.Request(
        POSTHOG_BATCH_URL,
        data=json.dumps({"api_key": token, "batch": events}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- the URL is the module constant above, not input
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
        pass


def main() -> int:
    env = os.environ
    match = DEPOT_JOB_URL.match(env.get("DEPOT_JOB_URL", ""))
    if not match:
        sys.stdout.write("::error::DEPOT_JOB_URL does not name a Depot workflow\n")
        return 1
    workflow_url, org, workflow_id = match.groups()
    shown = json.loads(
        subprocess.run(
            ["depot", "ci", "workflow", "show", workflow_id, "--org", org, "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    events = build_events(shown, workflow_url, env["STATUS_JOB"], env, dt.datetime.now(dt.UTC))
    failed = False
    for token_name in ("POSTHOG_API_TOKEN", "POSTHOG_DEVEX_PROJECT_API_TOKEN"):
        token = env.get(token_name)
        if not token:
            sys.stdout.write(f"::warning::{token_name} is not set, so its project gets no events\n")
            continue
        try:
            send_batch(token, events)
        except OSError as error:
            sys.stdout.write(f"::warning::Sending events with {token_name} failed: {error}\n")
            failed = True
            continue
        sys.stdout.write(f"Sent {len(events)} events with {token_name}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
