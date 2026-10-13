#!/usr/bin/env python3
"""Decide which CI engine runs a Backend CI event: GitHub Actions or Depot CI.

Only GitHub Actions runs this script. Its answer drives the `Hand off backend tests
to Depot CI` job, which Depot CI waits for before it runs anything, so Depot never
routes on its own and the tests never run on both engines. Once that job has concluded
for a commit, every later run of the same commit repeats its answer, whatever the
percent or the labels say by then, even after the rollout variable is deleted. A read of
that record that keeps failing stops routing, so a commit cannot run on both engines.

Any other event goes to Depot only after Depot started a run for it. Depot compiles its run
from the pull request's merge ref as soon as the event arrives, while GitHub Actions waits
until GitHub has updated that ref. When the ref is missing, Depot ends the run with no
workflows; when it stays stale, Depot fails to compile. Depot also cancels some runs under
its concurrency policy before they start. Each case leaves the event with no Depot run, so
it stays here.

Merge queue batches have their own percent, CI_BACKEND_DEPOT_MERGE_QUEUE_PERCENT, so the
merge gate moves to Depot separately from source pull requests. Batches ignore the routing
labels, so setting that percent to 0 keeps every new batch on GitHub Actions.
"""

import os
import sys
import json
import time
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ci_backend_relay import (
    EVENT_TIME,
    MIRROR_APP_ID,
    CheckReader,
    CheckRunReader,
    ReadFailedError,
    ReadRefusedError,
    event_check_name,
    is_merge_queue,
)

LABEL_FORCE_GITHUB = "ci-backend-github"
LABEL_FORCE_DEPOT = "ci-backend-depot"
PERCENT_VARIABLE = "CI_BACKEND_DEPOT_PERCENT"
HANDOFF_CHECK = "Hand off backend tests to Depot CI"
GITHUB_ACTIONS_APP_ID = 15368
ENGINE_BY_HANDOFF_CONCLUSION = {"success": "depot", "skipped": "github"}
API_ROOT = "https://api.github.com"
API_ATTEMPTS = 3
API_BACKOFF_SECONDS = 5
# The first step of Depot's wait job in .depot/workflows/ci-backend.yml posts this check; change both.
STARTED_JOB = "Depot run started"
# How long after the event Depot's wait job may take to start before the event stays on GitHub Actions.
DEPOT_START_SECONDS = 180
DEPOT_POLL_SECONDS = 10


class HandoffReadError(RuntimeError):
    """The durable routing record could not be read, so the event must not be routed."""


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


def bucket_of(pr_number: int) -> int:
    """The pull request's fixed rollout bucket, 0 to 99.

    Pull request numbers are sequential, so `pr_number % 100` would give Depot runs of
    consecutive pull requests and then none for the next 95. A hash spreads them while
    every push to one pull request keeps its bucket. Python's `hash()` is salted per
    process, so it would move a pull request between engines from one run to the next.
    """
    return int.from_bytes(hashlib.sha256(str(pr_number).encode()).digest()[:8], "big") % 100


def handoff_conclusion(check_runs: list[dict], pr_number: int) -> str | None:
    """The hand-off conclusion that already committed an engine to this commit for this pull request.

    A `success` means Depot ran the tests and a `skipped` means GitHub Actions did, and
    neither is undone by a later attempt that was cancelled or re-routed, so the first
    of those found wins over anything newer. GitHub queues a fresh check for every
    attempt, so only concluded ones count, and the API lists every pull request's checks
    for a head SHA, so only this one's count.
    """
    conclusions = [
        run.get("conclusion")
        for run in sorted(check_runs, key=lambda run: run["id"], reverse=True)
        if run.get("status") == "completed"
        and any(pr.get("number") == pr_number for pr in run.get("pull_requests") or [])
    ]
    for committed in ENGINE_BY_HANDOFF_CONCLUSION:
        if committed in conclusions:
            return committed
    return conclusions[0] if conclusions else None


def by_bucket(pr_number: int | None, percent: int, label: str) -> Decision:
    if pr_number is None:
        return Decision("github", "no pull request number to hash")
    bucket = bucket_of(pr_number)
    if bucket < percent:
        return Decision("depot", f"{label} {bucket} < {percent}%")
    return Decision("github", f"{label} {bucket} >= {percent}%")


def decide(
    event: str,
    percent: int,
    pr_number: int | None,
    labels: list[str],
    is_fork: bool,
    is_draft: bool,
    prior_handoff: str | None = None,
    head_ref: str = "",
    merge_queue_percent: int = 0,
) -> Decision:
    if event != "pull_request":
        return Decision("github", f"{event} events stay on GitHub Actions")
    prior_engine = ENGINE_BY_HANDOFF_CONCLUSION.get(prior_handoff or "")
    if prior_engine:
        return Decision(prior_engine, f"an earlier run of this commit chose {prior_engine}")
    if is_merge_queue(head_ref):
        return by_bucket(pr_number, merge_queue_percent, "merge queue bucket")
    if LABEL_FORCE_GITHUB in labels:
        return Decision("github", f"label {LABEL_FORCE_GITHUB}")
    if is_fork:
        return Decision("github", "fork pull requests never run on Depot")
    if is_draft and "no-ci" in labels:
        return Decision("github", "no-ci drafts skip on GitHub Actions and run nowhere else")
    if LABEL_FORCE_DEPOT in labels:
        return Decision("depot", f"label {LABEL_FORCE_DEPOT}")
    return by_bucket(pr_number, percent, "bucket")


def fetch_handoff_checks(repo: str, sha: str, token: str, *, opener: Any = None) -> list[dict]:
    """GET this commit's hand-off check runs, retrying transient failures only.

    5xx and network errors are worth another attempt; 4xx is not, because with an
    empty rate-limit bucket or a missing permission a retry only spends more of it.
    """
    query = urllib.parse.urlencode(
        {"check_name": HANDOFF_CHECK, "app_id": GITHUB_ACTIONS_APP_ID, "filter": "all", "per_page": 100}
    )
    url = f"{API_ROOT}/repos/{repo}/commits/{sha}/check-runs?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        },
    )
    do_open = opener or urllib.request.urlopen
    for attempt in range(1, API_ATTEMPTS + 1):
        try:
            with do_open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))["check_runs"]
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == API_ATTEMPTS:
                raise HandoffReadError(f"GET {url} failed with {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError) as error:
            if attempt == API_ATTEMPTS:
                raise HandoffReadError(f"GET {url} failed: {error}") from error
        sys.stdout.write(f"::warning::Cannot read the earlier hand-off yet ({attempt}/{API_ATTEMPTS})\n")
        time.sleep(API_BACKOFF_SECONDS * attempt)
    raise HandoffReadError(f"GET {url} exhausted {API_ATTEMPTS} attempts")


def depot_started(
    reader: CheckReader,
    pr_number: int,
    event_at: str,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Whether Depot started a run for this event, waiting up to DEPOT_START_SECONDS after it.

    The started check names the event, so it identifies this event's run and no other.
    """
    try:
        deadline = datetime.strptime(event_at, EVENT_TIME).replace(tzinfo=UTC).timestamp() + DEPOT_START_SECONDS
    except ValueError:
        return False
    name = event_check_name(STARTED_JOB, pr_number, event_at)
    while True:
        try:
            if reader.read(name):
                return True
        except ReadFailedError:
            pass
        except ReadRefusedError:
            return False
        if clock() >= deadline:
            return False
        sleep(DEPOT_POLL_SECONDS)


def main() -> int:
    env = os.environ
    event = env.get("EVENT", "")
    pr_raw = env.get("PR_NUMBER", "")
    pr_number = int(pr_raw) if pr_raw.isdigit() else None
    is_fork = env.get("IS_FORK", "false") == "true"
    labels = json.loads(env.get("LABELS") or "null") or []

    def route_with(prior_handoff: str | None) -> Decision:
        return decide(
            event=event,
            percent=parse_percent(env.get("PERCENT")),
            pr_number=pr_number,
            labels=labels,
            is_fork=is_fork,
            is_draft=env.get("IS_DRAFT", "false") == "true",
            prior_handoff=prior_handoff,
            head_ref=env.get("HEAD_REF", ""),
            merge_queue_percent=parse_percent(env.get("MERGE_QUEUE_PERCENT")),
        )

    prior_handoff = None
    if event == "pull_request" and pr_number is not None and not is_fork:
        try:
            prior_handoff = handoff_conclusion(
                fetch_handoff_checks(env["REPO"], env["SHA"], env["GH_TOKEN"]), pr_number
            )
        except HandoffReadError as error:
            sys.stdout.write(f"::error::Cannot read the earlier hand-off, so this event is not routed: {error}\n")
            return 1
        else:
            sys.stdout.write(f"::notice::Earlier hand-off on this commit: {prior_handoff or 'none'}\n")
    decision = route_with(prior_handoff)
    if (
        decision.engine == "depot"
        and prior_handoff not in ENGINE_BY_HANDOFF_CONCLUSION
        and pr_number is not None
        and not depot_started(
            CheckRunReader(env["REPO"], env["SHA"], env["GH_TOKEN"], pr_number=pr_number, app_ids=(MIRROR_APP_ID,)),
            pr_number,
            env.get("EVENT_AT", ""),
        )
    ):
        decision = Decision("github", "Depot CI started no run for this event")
    sys.stdout.write(f"::notice::Backend CI engine: {decision.engine} ({decision.reason})\n")
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"engine={decision.engine}\nreason={decision.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
