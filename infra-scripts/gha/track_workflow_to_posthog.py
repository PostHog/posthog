import os
import requests
from datetime import datetime

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

headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

jobs_resp = requests.get(
    f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{RUN_ID}/jobs?per_page=100",
    headers=headers,
    timeout=30,
)
jobs_resp.raise_for_status()
jobs = jobs_resp.json().get("jobs", [])

events = []
for job in jobs:
    for step in job.get("steps", []):
        started = step.get("started_at")
        completed = step.get("completed_at")
        duration = None
        if started and completed:
            try:
                start_time = datetime.fromisoformat(started.replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                duration = (end_time - start_time).total_seconds()
            except Exception:
                pass
        events.append(
            {
                "event": "github action step",
                "properties": {
                    "workflow": WORKFLOW,
                    "job": job.get("name"),
                    "step": step.get("name"),
                    "conclusion": step.get("conclusion"),
                    "run_id": RUN_ID,
                    "run_number": RUN_NUMBER,
                    "run_attempt": RUN_ATTEMPT,
                    "pr_number": os.environ.get("GITHUB_REF", "").split("/")[-1]
                    if os.environ.get("GITHUB_REF", "").startswith("refs/pull/")
                    else None,
                    "sha": os.environ.get("GITHUB_SHA"),
                    "duration_seconds": duration,
                },
                "distinct_id": ACTOR,
                "timestamp": completed or started,
            }
        )

if not events:
    print("No jobs or steps found")  # noqa: T201
    exit(0)

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
