#!/usr/bin/env python3
"""Follow the Depot CI run that took over one pull request event, and read one of its checks.

GitHub Actions hands a pull request event to Depot CI (see ci_backend_route.py), and Depot
starts a workflow for every pull request event. One commit can therefore carry Depot runs of
earlier events, a duplicate run of the same event, and runs of another pull request with the
same head. Depot check times and pull request lists cannot tell them apart:

- When Depot cancels a superseded run, it posts a cancelled check for each job that had not
  started, with `started_at` set to the cancel time.
- Depot's checks sit in its app's check suite for the commit, which carries the branch of the
  commit's first push. When that branch is not the pull request's head, the checks list no
  pull request.

.agents/skills/depot-ci/references/posthog-check-run-semantics.md has the measurements.
So the Depot wait job's check name carries the event: the pull request number and its
`updated_at`, which both engines read from the same event payload. That check identifies the
event's run, and every other check of the run is matched by the Depot workflow id in its
details URL.

Standard library only: the relay job runs this with the runner's python3 before any install.
"""

import os
import re
import sys
import json
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

DEPOT_APP_ID = 219785
DEPOT_WORKFLOW = "Backend CI on Depot"
WAIT_JOB = "Wait for GitHub Actions to hand off backend tests"
# Renders the same text as the wait job's name expression in .depot/workflows/ci-backend.yml.
EVENT_SUFFIX = " (PR {pr}, event {event_at})"
GATE_CHECK = f"{DEPOT_WORKFLOW} / Django Tests Pass on Depot"
MIGRATION_CHECK = f"{DEPOT_WORKFLOW} / Validate migrations"
CHANGES_CHECK = f"{DEPOT_WORKFLOW} / Determine need to run backend and migration checks"
HANDOFF_CHECK = "Hand off backend tests to Depot CI"
GITHUB_ACTIONS_APP_ID = 15368
DEPOT_RUN_URL = re.compile(r"^https://depot\.dev/orgs/([^/?]+)/workflows/([a-z0-9]+)(?:[?/]|$)")
PENDING_STATES = frozenset({"queued", "in_progress", "pending", "waiting", "requested"})
API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
# A 403 also covers a secondary rate limit, which clears, so a few refusals in a row are tolerated.
MAX_REFUSALS = 5


class ReadRefusedError(RuntimeError):
    """The check-runs API keeps refusing the token, so no verdict can be read."""


class HandoffUnresolvedError(RuntimeError):
    """The report cannot determine which engine owns this event."""


@dataclass(frozen=True)
class CheckRun:
    id: int
    # The conclusion once the check completed, its status before that.
    state: str
    pull_requests: frozenset[int]
    details_url: str

    @classmethod
    def from_api(cls, run: dict[str, Any]) -> "CheckRun":
        return cls(
            id=int(run["id"]),
            state=str((run.get("conclusion") if run.get("status") == "completed" else run.get("status")) or ""),
            pull_requests=frozenset(int(pr["number"]) for pr in run.get("pull_requests") or []),
            details_url=str(run.get("details_url") or ""),
        )

    @property
    def depot_workflow(self) -> str | None:
        match = DEPOT_RUN_URL.match(self.details_url)
        return match.group(2) if match else None


class Phase(Enum):
    ABSENT = "absent"
    STARTING = "starting"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    RUNNING = "running"
    FINISHED = "finished"


@dataclass(frozen=True)
class Progress:
    phase: Phase
    # The state of the check behind the phase, empty when there is none.
    state: str = ""
    details_url: str = ""


def wait_check_name(pr_number: int, event_at: str) -> str:
    return f"{DEPOT_WORKFLOW} / {WAIT_JOB}{EVENT_SUFFIX.format(pr=pr_number, event_at=event_at)}"


def newest_live(runs: Sequence[CheckRun]) -> CheckRun | None:
    """The newest run that was not cancelled, or the newest cancelled run when every run was."""
    live = [run for run in runs if run.state != "cancelled"]
    return max(live or runs, key=lambda run: run.id, default=None)


def handoff_decision(runs: Iterable[CheckRun], pr_number: int) -> bool | None:
    """Mirror the router's durable decision for this pull request and commit."""
    states = {run.state for run in runs if pr_number in run.pull_requests}
    if "success" in states:
        return True
    if "skipped" in states:
        return False
    return None


def progress(
    wait: CheckRun | None, checks: Iterable[CheckRun], skipped_dependency_checks: Iterable[CheckRun] = ()
) -> Progress:
    """Where the Depot run behind `wait` stands, judged by its check among `checks`."""
    if wait is None:
        return Progress(Phase.ABSENT)
    if wait.state == "cancelled":
        return Progress(Phase.CANCELLED, wait.state, wait.details_url)
    if wait.state in PENDING_STATES:
        return Progress(Phase.STARTING, wait.state, wait.details_url)
    if wait.state != "success":
        return Progress(Phase.DECLINED, wait.state, wait.details_url)
    workflow = wait.depot_workflow
    # A retried Depot job posts a new check in the same workflow, so the newest one is current.
    check = max(
        (run for run in checks if workflow is not None and run.depot_workflow == workflow),
        key=lambda run: run.id,
        default=None,
    )
    if check is None:
        dependency = max(
            (run for run in skipped_dependency_checks if workflow is not None and run.depot_workflow == workflow),
            key=lambda run: run.id,
            default=None,
        )
        if dependency is not None and dependency.state == "skipped":
            return Progress(Phase.DECLINED, dependency.state, dependency.details_url)
    if check is None or check.state in PENDING_STATES:
        return Progress(Phase.RUNNING, check.state if check else "", wait.details_url)
    if check.state == "cancelled":
        return Progress(Phase.CANCELLED, check.state, check.details_url)
    return Progress(Phase.FINISHED, check.state, check.details_url)


class CheckReader(Protocol):
    def read(self, name: str) -> list[CheckRun]: ...


class CheckRunReader:
    """Reads one commit's check runs for one app by name, with conditional requests.

    A 304 answer is free against the rate limit, so polling stays cheap.
    """

    def __init__(
        self,
        repo: str,
        sha: str,
        token: str,
        opener: Callable[..., Any] = urllib.request.urlopen,
        app_id: int = DEPOT_APP_ID,
    ) -> None:
        self._repo = repo
        self._sha = sha
        self._token = token
        self._opener = opener
        self._app_id = app_id
        self._cache: dict[str, tuple[str, list[CheckRun]]] = {}
        self._refusals = 0

    def _url(self, name: str, page: int) -> str:
        query = urllib.parse.urlencode(
            {"check_name": name, "app_id": self._app_id, "filter": "all", "per_page": PAGE_SIZE, "page": page}
        )
        return f"{API_ROOT}/repos/{self._repo}/commits/{self._sha}/check-runs?{query}"

    def _get(self, url: str, etag: str = "") -> tuple[int, str, dict[str, Any]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {self._token}",
        }
        if etag:
            headers["If-None-Match"] = etag
        try:
            with self._opener(urllib.request.Request(url, headers=headers), timeout=30) as response:
                return response.status, response.headers.get("ETag", ""), json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, "", {}

    def read(self, name: str) -> list[CheckRun]:
        """Read every page, reusing a cached answer only when the API confirms it with 304."""
        etag, cached = self._cache.get(name, ("", []))
        raw: list[dict[str, Any]] = []
        page = 1
        new_etag = ""
        try:
            while True:
                code, page_etag, body = self._get(self._url(name, page), etag if page == 1 else "")
                if page == 1 and code == 304:
                    self._refusals = 0
                    return cached
                if code in (401, 403):
                    self._refusals += 1
                    if self._refusals >= MAX_REFUSALS:
                        raise ReadRefusedError(f"Cannot read checks for {self._sha}")
                if code != 200:
                    sys.stdout.write(f"::warning::check-runs API returned {code}\n")
                    return []
                self._refusals = 0
                if page == 1:
                    new_etag = page_etag
                batch = body["check_runs"]
                raw.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                page += 1
        except (OSError, http.client.HTTPException, ValueError) as error:
            sys.stdout.write(f"::warning::check-runs API read failed: {error}\n")
            return []
        runs = [CheckRun.from_api(run) for run in raw]
        # One page's ETag cannot validate the other pages of a paginated response.
        self._cache[name] = (new_etag if page == 1 else "", runs)
        return runs


@dataclass(frozen=True)
class Event:
    repo: str
    sha: str
    pr_number: int
    # The pull request's `updated_at` in this event's payload.
    event_at: str


def wait_for_handoff(
    reader: CheckReader,
    event: Event,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """The router's committed engine; an unread decision cannot suppress a report."""
    start = clock()
    while True:
        decision = handoff_decision(reader.read(HANDOFF_CHECK), event.pr_number)
        if decision is not None:
            return decision
        if clock() - start >= 10 * 60:
            raise HandoffUnresolvedError(f"Cannot determine the backend hand-off for {event.sha}")
        sleep(20)


def poll(
    reader: CheckReader,
    event: Event,
    check_name: str,
    *,
    deadline_minutes: int,
    absent_minutes: int,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Progress:
    """Polls until the event's check finishes, Depot declines the hand-off, or a deadline passes.

    A duplicate run of the same event can replace a cancelled one. The migration report
    gives an absent or cancelled run the full deadline; the required gate uses a shorter grace period.
    """
    start = clock()
    event_name = wait_check_name(event.pr_number, event.event_at)
    while True:
        wait = newest_live(reader.read(event_name))
        checks = reader.read(check_name) if wait and wait.state == "success" else []
        dependencies = (
            reader.read(CHANGES_CHECK) if check_name == MIGRATION_CHECK and wait and wait.state == "success" else []
        )
        current = progress(wait, checks, dependencies)
        sys.stdout.write(f"Depot run for this event: {current.phase.value} {current.state}".rstrip() + "\n")
        elapsed = clock() - start
        if current.phase in (Phase.FINISHED, Phase.DECLINED):
            return current
        if current.phase in (Phase.ABSENT, Phase.CANCELLED) and elapsed >= absent_minutes * 60:
            return current
        if elapsed >= deadline_minutes * 60:
            return current
        # The checked job only posts its check when the matrix is done, so once Depot has
        # started, a slower poll costs at most a minute of latency.
        sleep(60 if current.phase == Phase.RUNNING else 30)


def retry_instructions(event: Event, details_url: str, run_id: str) -> list[str]:
    lines = [
        f"Backend tests for {event.sha} ran on Depot CI, not GitHub Actions. Re-running this job alone reads the same result.",
        f"Depot run: {details_url or 'not found'}",
        "",
    ]
    match = DEPOT_RUN_URL.match(details_url)
    if match:
        org, workflow = match.groups()
        lines += [
            f"Retry through the Depot CLI (needs access to the Depot org {org}):",
            f"  depot ci diagnose --org {org} --workflow {workflow}   # the failures, and the run ID on the 'Run:' line",
            f"  depot ci retry <run ID> --org {org} --workflow {workflow} --failed",
            f"  depot ci status <run ID> --org {org}   # repeat until the run finishes",
            f"  gh run rerun {run_id} --repo {event.repo} --failed   # relays the new Depot result",
            "",
        ]
    return [
        *lines,
        "Retry without Depot access: a new commit starts a fresh run.",
        "  git commit --allow-empty -m 'chore: retry backend ci' && git push",
        "",
        "Run on GitHub Actions instead: the ci-backend-github label routes the next commit of this PR there.",
        f"  gh pr edit {event.pr_number} --repo {event.repo} --add-label ci-backend-github",
        "  git commit --allow-empty -m 'chore: retry backend ci on github actions' && git push",
    ]


def relay_gate(result: Progress, event: Event, run_id: str) -> tuple[int, list[str]]:
    """The exit code and log lines of the `Django Tests Pass` relay for the gate's progress."""
    if result.phase == Phase.FINISHED and result.state == "success":
        return 0, []
    if result.phase == Phase.FINISHED:
        return 1, [
            f"::error::Backend tests on Depot CI concluded {result.state}. This step's log lists the retry options.",
            *retry_instructions(event, result.details_url, run_id),
        ]
    if result.phase == Phase.CANCELLED:
        return 1, [
            f"::error::Depot CI cancelled its run for this event of {event.sha} and started no replacement.",
            *retry_instructions(event, result.details_url, run_id),
        ]
    if result.phase == Phase.DECLINED:
        return 1, [f"::error::Depot declined the hand-off for {event.sha} (wait job: {result.state})"]
    if result.phase == Phase.ABSENT:
        return 1, [f"::error::Depot CI started no run for this event of {event.sha}: no wait job for it"]
    return 1, [f"::error::No Depot verdict for {event.sha} within the relay's deadline"]


def report_migrations(result: Progress) -> tuple[int, list[str], dict[str, str]]:
    """The exit code, log lines and step outputs of the migration report's source step."""
    if result.phase == Phase.FINISHED and result.state in ("success", "failure", "neutral"):
        match = DEPOT_RUN_URL.match(result.details_url)
        if not match:
            return 1, ["::error::Unexpected Depot migration check URL"], {}
        return 0, [], {"migration_state": result.state, "workflow_id": match.group(2)}
    if result.phase in (Phase.FINISHED, Phase.CANCELLED) and result.state in ("skipped", "cancelled"):
        return 0, [f"No completed migration report is available (migration check: {result.state})."], {}
    if result.phase == Phase.FINISHED:
        return 1, [f"::error::Unexpected migration check state: {result.state}"], {}
    if result.phase == Phase.ABSENT:
        return 1, ["::error::Depot posted no event-matched wait check after a confirmed hand-off"], {}
    if result.phase == Phase.DECLINED:
        return 0, [f"Depot CI ran no backend tests for this event ({result.phase.value} {result.state})."], {}
    return 1, ["::error::Depot migration check did not finish within the report's deadline"], {}


def main(argv: Sequence[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    env = os.environ
    event = Event(repo=env["REPO"], sha=env["SHA"], pr_number=int(env["PR_NUMBER"]), event_at=env["EVENT_AT"])
    reader = CheckRunReader(event.repo, event.sha, env["GH_TOKEN"])
    try:
        if mode == "gate":
            result = poll(reader, event, GATE_CHECK, deadline_minutes=90, absent_minutes=15)
            code, lines = relay_gate(result, event, env.get("GITHUB_RUN_ID", ""))
            outputs: dict[str, str] = {}
        elif mode == "migrations":
            handoff_reader = CheckRunReader(event.repo, event.sha, env["GH_TOKEN"], app_id=GITHUB_ACTIONS_APP_ID)
            if wait_for_handoff(handoff_reader, event):
                result = poll(reader, event, MIGRATION_CHECK, deadline_minutes=70, absent_minutes=70)
            else:
                result = Progress(Phase.DECLINED, "skipped")
            code, lines, outputs = report_migrations(result)
        else:
            sys.stderr.write("usage: ci_backend_relay.py gate|migrations\n")
            return 2
    except (ReadRefusedError, HandoffUnresolvedError) as error:
        sys.stdout.write(f"::error::{error}\n")
        return 1
    sys.stdout.writelines(f"{line}\n" for line in lines)
    output_path = env.get("GITHUB_OUTPUT")
    if output_path and outputs:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
