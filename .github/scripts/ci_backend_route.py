#!/usr/bin/env python3
"""Decide which CI engine runs a Backend CI event: GitHub Actions or Depot CI.

Only GitHub Actions runs this script. Its answer drives the `Hand off backend tests
to Depot CI` job, which Depot CI waits for before it runs anything, so Depot never
routes on its own and the tests never run on both engines. Once that job has concluded
for a commit, every later run of the same commit repeats its answer, whatever the
percent or the labels say by then. A read of that record that keeps failing fails the
run, so nothing is routed anywhere.
"""

import os
import sys
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

LABEL_FORCE_GITHUB = "ci-backend-github"
LABEL_FORCE_DEPOT = "ci-backend-depot"
PERCENT_VARIABLE = "CI_BACKEND_DEPOT_PERCENT"
HANDOFF_CHECK = "Hand off backend tests to Depot CI"
GITHUB_ACTIONS_APP_ID = 15368
ENGINE_BY_HANDOFF_CONCLUSION = {"success": "depot", "skipped": "github"}


@dataclass(frozen=True)
class Decision:
    engine: str
    reason: str


def parse_percent(raw: str | None) -> int:
    value = raw.strip() if raw is not None else ""
    # isdecimal() accepts digits int() rejects, and int() refuses very long strings.
    if not value.isascii() or not value.isdecimal():
        return 0
    try:
        return min(int(value), 100)
    except ValueError:
        return 0


def handoff_conclusion(check_runs: list[dict], pr_number: int) -> str | None:
    """Conclusion of the newest concluded hand-off check on this commit for this pull request.

    GitHub queues a fresh check for every attempt, so only concluded ones count, and the
    API lists every pull request's checks for a head SHA, so only this one's count.
    """
    concluded = [
        run
        for run in check_runs
        if run.get("status") == "completed"
        and any(pr.get("number") == pr_number for pr in run.get("pull_requests") or [])
    ]
    if not concluded:
        return None
    return max(concluded, key=lambda run: run["id"]).get("conclusion")


def decide(
    event: str,
    percent: int,
    pr_number: int | None,
    labels: list[str],
    is_fork: bool,
    is_draft: bool,
    prior_handoff: str | None = None,
) -> Decision:
    if event != "pull_request":
        return Decision("github", f"{event} events stay on GitHub Actions")
    prior_engine = ENGINE_BY_HANDOFF_CONCLUSION.get(prior_handoff or "")
    if prior_engine:
        return Decision(prior_engine, f"an earlier run of this commit chose {prior_engine}")
    if LABEL_FORCE_GITHUB in labels:
        return Decision("github", f"label {LABEL_FORCE_GITHUB}")
    if is_fork:
        return Decision("github", "fork pull requests never run on Depot")
    if is_draft and "no-ci" in labels:
        return Decision("github", "no-ci drafts skip on GitHub Actions and run nowhere else")
    if LABEL_FORCE_DEPOT in labels:
        return Decision("depot", f"label {LABEL_FORCE_DEPOT}")
    if pr_number is None:
        return Decision("github", "no pull request number to hash")
    bucket = pr_number % 100
    if bucket < percent:
        return Decision("depot", f"bucket {bucket} < {percent}%")
    return Decision("github", f"bucket {bucket} >= {percent}%")


def fetch_handoff_checks(repo: str, sha: str, token: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {"check_name": HANDOFF_CHECK, "app_id": GITHUB_ACTIONS_APP_ID, "filter": "all", "per_page": 100}
    )
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    # The scheme and host are literal; only the repo and commit come from the event.
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["check_runs"]


def read_prior_handoff(
    fetch: Callable[[], list[dict]], pr_number: int, attempts: int = 3, pause_seconds: float = 10
) -> str | None:
    for attempt in range(1, attempts + 1):
        try:
            return handoff_conclusion(fetch(), pr_number)
        except (OSError, ValueError, KeyError, TypeError) as error:
            sys.stdout.write(f"::warning::Cannot read the earlier hand-off ({attempt}/{attempts}): {error}\n")
            if attempt < attempts:
                time.sleep(pause_seconds)
    raise RuntimeError("Cannot read the earlier hand-off for this commit, so this event is not routed")


def main() -> int:
    env = os.environ
    event = env.get("EVENT", "")
    pr_raw = env.get("PR_NUMBER", "")
    pr_number = int(pr_raw) if pr_raw.isdigit() else None
    is_fork = env.get("IS_FORK", "false") == "true"
    prior_handoff = None
    if event == "pull_request" and pr_number is not None and not is_fork:
        try:
            prior_handoff = read_prior_handoff(
                lambda: fetch_handoff_checks(env["REPO"], env["SHA"], env["GH_TOKEN"]), pr_number
            )
        except RuntimeError as error:
            sys.stdout.write(f"::error::{error}\n")
            return 1
        sys.stdout.write(f"::notice::Earlier hand-off on this commit: {prior_handoff or 'none'}\n")
    decision = decide(
        event=event,
        percent=parse_percent(env.get("PERCENT")),
        pr_number=pr_number,
        labels=json.loads(env.get("LABELS") or "null") or [],
        is_fork=is_fork,
        is_draft=env.get("IS_DRAFT", "false") == "true",
        prior_handoff=prior_handoff,
    )
    sys.stdout.write(f"::notice::Backend CI engine: {decision.engine} ({decision.reason})\n")
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"engine={decision.engine}\nreason={decision.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
