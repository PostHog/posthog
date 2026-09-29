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

Two events of one commit that arrive within a second or two race the concurrency cancel of
both engines, and each engine can keep a different event. GitHub Actions alone can also keep
either event of such a pair, so when this event has no live Depot run, the relay follows the
run that Depot kept for the racing event.

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
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

DEPOT_APP_ID = 219785
DEPOT_ORG = "ntsdt08fpt"
# The PostHog tests GitHub App. Depot's wait and gate jobs post the same checks with it, because
# Depot posts its own checks from a budget that runs out at peak and then delivers them late.
MIRROR_APP_ID = 2492437
DEPOT_WORKFLOW = "Backend CI on Depot"
WAIT_JOB = "Wait for GitHub Actions to hand off backend tests"
# Renders the same text as the wait job's name expression in .depot/workflows/ci-backend.yml.
EVENT_SUFFIX = " (PR {pr}, event {event_at})"
# How a pull request event payload renders `updated_at`.
EVENT_TIME = "%Y-%m-%dT%H:%M:%SZ"
RACING_EVENT_SECONDS = 2
GATE_CHECK = f"{DEPOT_WORKFLOW} / Django Tests Pass on Depot"
DEPOT_RUN_URL = re.compile(r"^https://depot\.dev/orgs/([^/?]+)/workflows/([a-z0-9]+)(?:[?/]|$)")
PENDING_STATES = frozenset({"queued", "in_progress", "pending", "waiting", "requested"})
CONCLUSIONS = frozenset(
    {
        "success",
        "failure",
        "cancelled",
        "skipped",
        "timed_out",
        "neutral",
        "action_required",
        "stale",
        "startup_failure",
    }
)
API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
# A 403 also covers a secondary rate limit, which clears, so a few refusals in a row are tolerated.
MAX_REFUSALS = 5
PREREQUISITES = ("Repo checks (depot-ubuntu-24.04)", "Validate OpenAPI types")


class ReadRefusedError(RuntimeError):
    """The check-runs API keeps refusing the token, so no verdict can be read."""


class ReadFailedError(RuntimeError):
    """One read of the check-runs API failed, so this poll cannot tell which checks exist."""


@dataclass(frozen=True)
class CheckRun:
    id: int
    # The conclusion once the check completed, its status before that.
    state: str
    details_url: str
    app_id: int = DEPOT_APP_ID
    # The job attempt in a mirrored check's URL. Depot's own checks carry none.
    attempt: str = ""

    @classmethod
    def from_api(cls, run: dict[str, Any]) -> "CheckRun":
        state = (run.get("conclusion") if run.get("status") == "completed" else run.get("status")) or ""
        url = str(run.get("details_url") or "")
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        match = re.fullmatch(rf"/orgs/{re.escape(DEPOT_ORG)}/workflows/([a-z0-9]+)", parsed.path)
        attempt = ""
        if parsed.scheme == "https" and parsed.netloc == "depot.dev" and match:
            job = query.get("job", [""])[0]
            url = f"https://depot.dev/orgs/{DEPOT_ORG}/workflows/{match[1]}"
            if re.fullmatch(r"[a-z0-9]+", job):
                url += f"?job={job}"
            attempt = query.get("attempt", [""])[0]
        else:
            url = ""
        return cls(
            id=int(run["id"]),
            state=state if state in PENDING_STATES | CONCLUSIONS else "unknown",
            details_url=url,
            app_id=int(run["app"]["id"]),
            attempt=attempt if re.fullmatch(r"[a-z0-9]+", attempt) else "",
        )

    @property
    def depot_workflow(self) -> str | None:
        match = DEPOT_RUN_URL.match(self.details_url)
        return match.group(2) if match and match.group(1) == DEPOT_ORG else None


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
    root_failure: str = ""
    root_check_id: int = 0
    check_id: int = 0


def wait_check_name(pr_number: int, event_at: str) -> str:
    return f"{DEPOT_WORKFLOW} / {WAIT_JOB}{EVENT_SUFFIX.format(pr=pr_number, event_at=event_at)}"


def current_check(checks: Iterable[CheckRun], workflow: str | None) -> CheckRun | None:
    """The check of the newest attempt of one job in `workflow`, from either app that posts it.

    Depot posts one check per job attempt but can deliver it late, so its check ids do not order
    its checks against the mirror's. The mirror posts one check per attempt that ran, in order,
    but a post can fail. The mirror decides while it has posted at least as many attempts as
    Depot shows. Otherwise the mirror missed an attempt, and Depot's newest check decides.
    """
    own = [check for check in checks if workflow is not None and check.depot_workflow == workflow]
    mirrored = [check for check in own if check.app_id == MIRROR_APP_ID]
    native = [check for check in own if check.app_id != MIRROR_APP_ID]
    if mirrored and len(native) <= len({check.attempt or str(check.id) for check in mirrored}):
        return max(mirrored, key=lambda check: check.id)
    return max(native, key=lambda check: check.id, default=None)


def newest_live(runs: Sequence[CheckRun]) -> CheckRun | None:
    """The newest run that was not cancelled, or the newest cancelled run when every run was."""
    current = [check for workflow in {run.depot_workflow for run in runs} if (check := current_check(runs, workflow))]
    live = [run for run in current if run.state != "cancelled"]
    return max(live or current, key=lambda run: run.id, default=None)


def progress(wait: CheckRun | None, checks: Iterable[CheckRun]) -> Progress:
    """Where the Depot run behind `wait` stands, judged by its check among `checks`."""
    if wait is None:
        return Progress(Phase.ABSENT)
    if wait.state == "cancelled":
        return Progress(Phase.CANCELLED, wait.state, wait.details_url)
    if wait.state in PENDING_STATES:
        return Progress(Phase.STARTING, wait.state, wait.details_url)
    if wait.state != "success":
        return Progress(Phase.DECLINED, wait.state, wait.details_url)
    check = current_check(checks, wait.depot_workflow)
    if check is None or check.state in PENDING_STATES:
        return Progress(Phase.RUNNING, check.state if check else "", wait.details_url)
    if check.state == "cancelled":
        return Progress(Phase.CANCELLED, check.state, check.details_url, check_id=check.id)
    return Progress(Phase.FINISHED, check.state, check.details_url, check_id=check.id)


class CheckReader(Protocol):
    def read(self, name: str) -> list[CheckRun]: ...


class CheckRunReader:
    """Reads one commit's Depot check runs by name from each app that posts them, with conditional requests.

    A 304 answer is free against the rate limit, so polling stays cheap.
    """

    def __init__(
        self,
        repo: str,
        sha: str,
        token: str,
        opener: Callable[..., Any] = urllib.request.urlopen,
        pr_number: int | None = None,
        app_ids: Sequence[int] = (MIRROR_APP_ID, DEPOT_APP_ID),
    ) -> None:
        self._repo = repo
        self._sha = sha
        self._token = token
        self._pr_number = pr_number
        self._opener = opener
        self._app_ids = app_ids
        self._cache: dict[tuple[str, int], tuple[str, list[CheckRun]]] = {}
        self._refusals = 0

    def _url(self, name: str, app_id: int, page: int) -> str:
        query = urllib.parse.urlencode(
            {"check_name": name, "app_id": app_id, "filter": "all", "per_page": PAGE_SIZE, "page": page}
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
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("oversized check response")
                return response.status, response.headers.get("ETag", ""), json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, "", {}

    def read(self, name: str) -> list[CheckRun]:
        """Every app's checks of `name`. `current_check` picks the current one per workflow.

        A failed read of any app raises, because the other app's checks alone can hold a stale attempt.
        """
        runs: list[CheckRun] = []
        for app_id in self._app_ids:
            app_runs = self._read_app(name, app_id)
            if app_runs is None:
                raise ReadFailedError(f"Cannot read {name}")
            runs.extend(app_runs)
        return runs

    def _read_app(self, name: str, app_id: int) -> list[CheckRun] | None:
        """Read every page, reusing a cached answer only when the API confirms it with 304."""
        etag, cached = self._cache.get((name, app_id), ("", []))
        raw: list[dict[str, Any]] = []
        page = 1
        new_etag = ""
        try:
            while True:
                code, page_etag, body = self._get(self._url(name, app_id, page), etag if page == 1 else "")
                if page == 1 and code == 304:
                    self._refusals = 0
                    return cached
                if code in (401, 403):
                    self._refusals += 1
                    if self._refusals >= MAX_REFUSALS:
                        raise ReadRefusedError(f"Cannot read checks for {self._sha}")
                if code != 200:
                    sys.stdout.write(f"::warning::check-runs API returned {code}\n")
                    return None
                self._refusals = 0
                if page == 1:
                    new_etag = page_etag
                batch = body["check_runs"]
                if not isinstance(batch, list) or page > 20:
                    raise ValueError("invalid or excessive check pages")
                raw.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                page += 1
            runs = [
                CheckRun.from_api(run)
                for run in raw
                # One malformed record is skipped rather than discarding the whole answer.
                if isinstance(run, dict)
                and (run.get("app") or {}).get("id") == app_id
                and run.get("name") == name
                and run.get("head_sha") == self._sha
                and (
                    not run.get("pull_requests")
                    or self._pr_number is None
                    or any(pr.get("number") == self._pr_number for pr in run["pull_requests"])
                )
            ]
            runs = [run for run in runs if run.depot_workflow is not None]
        except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError, AttributeError):
            sys.stdout.write("::warning::check-runs API read failed\n")
            return None
        # One page's ETag cannot validate the other pages of a paginated response.
        self._cache[(name, app_id)] = (new_etag if page == 1 else "", runs)
        return runs


@dataclass(frozen=True)
class Event:
    repo: str
    sha: str
    pr_number: int
    # The pull request's `updated_at` in this event's payload.
    event_at: str


def racing_wait(reader: CheckReader, event: Event, followed: set[str]) -> str | None:
    """The newest racing wait check whose job took the hand-off or is pending, skipping `followed`."""
    event_at = datetime.strptime(event.event_at, EVENT_TIME)
    for offset in range(RACING_EVENT_SECONDS, -RACING_EVENT_SECONDS - 1, -1):
        name = wait_check_name(event.pr_number, (event_at + timedelta(seconds=offset)).strftime(EVENT_TIME))
        if name in followed:
            continue
        wait = newest_live(reader.read(name))
        if progress(wait, ()).phase in (Phase.STARTING, Phase.RUNNING):
            return name
    return None


def prerequisite_failure(reader: CheckReader, wait: CheckRun, current: Progress) -> Progress:
    for name in PREREQUISITES:
        latest = current_check(reader.read(f"{DEPOT_WORKFLOW} / {name}"), wait.depot_workflow)
        if latest and latest.state == "failure":
            return Progress(Phase.FINISHED, "failure", current.details_url, name, latest.id, current.check_id)
    return current


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

    A duplicate run of the same event can replace a cancelled one, so an absent or cancelled
    run gets `absent_minutes` of grace. After the grace period, the run of a racing event
    stands in for an absent or cancelled one.
    """
    start = clock()
    event_name = wait_check_name(event.pr_number, event.event_at)
    followed = {event_name}
    current = Progress(Phase.ABSENT)
    while True:
        try:
            wait = newest_live(reader.read(event_name))
            checks = reader.read(check_name) if wait and wait.state == "success" else []
            current = progress(wait, checks)
            # Depot cancels its own run only after a deterministic prerequisite failure. A gate that
            # failed without the cancel can follow a retryable one, so it keeps the retry options.
            if current.phase == Phase.CANCELLED and wait and wait.state == "success":
                current = prerequisite_failure(reader, wait, current)
            sys.stdout.write(f"Depot run for this event: {current.phase.value} {current.state}".rstrip() + "\n")
            elapsed = clock() - start
            if current.phase in (Phase.FINISHED, Phase.DECLINED):
                return current
            if current.phase in (Phase.ABSENT, Phase.CANCELLED) and elapsed >= absent_minutes * 60:
                racing = racing_wait(reader, event, followed)
                if racing is None:
                    return current
                sys.stdout.write(f"Depot kept a racing event of this commit instead. Following: {racing}\n")
                followed.add(racing)
                event_name = racing
                continue
        except ReadFailedError as error:
            # A failed read says nothing about the run, so it must not end the wait as absent.
            sys.stdout.write(f"::warning::{error}. Reading again.\n")
            elapsed = clock() - start
        if elapsed >= deadline_minutes * 60:
            return current
        # The checked job only posts its check when the matrix is done, so once Depot has
        # started, a slower poll costs at most a minute of latency.
        sleep(60 if current.phase == Phase.RUNNING else 30)


def retry_instructions(event: Event, details_url: str, run_id: str) -> list[str]:
    lines = [
        f"Backend tests for {event.sha} ran on Depot CI, not GitHub Actions. Re-running this job alone reads the same result.",
        f"Depot run: {details_url or 'not found'}",
        "Detailed failure evidence, when available, appears in the Backend Depot diagnostics check.",
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
        "Retryability: unknown without step or retry evidence. Inspect the failure before retrying.",
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
    if result.root_failure:
        return 1, [
            f"::error::{result.root_failure} failed on Depot (check {result.root_check_id}). "
            "Push a fix; a retry will not help."
        ]
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


def main(argv: Sequence[str]) -> int:
    if argv[1:] != ["gate"]:
        sys.stderr.write("usage: ci_backend_relay.py gate\n")
        return 2
    env = os.environ
    event = Event(repo=env["REPO"], sha=env["SHA"], pr_number=int(env["PR_NUMBER"]), event_at=env["EVENT_AT"])
    reader = CheckRunReader(event.repo, event.sha, env["GH_TOKEN"], pr_number=event.pr_number)
    try:
        result = poll(reader, event, GATE_CHECK, deadline_minutes=90, absent_minutes=15)
    except ReadRefusedError as error:
        sys.stdout.write(f"::error::{error}\n")
        return 1
    code, lines = relay_gate(result, event, env.get("GITHUB_RUN_ID", ""))
    sys.stdout.writelines(f"{line}\n" for line in lines)
    if code:
        if summary := env.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a") as stream:
                stream.write("\n".join(line.removeprefix("::error::") for line in lines) + "\n")
        if request := env.get("DEPOT_DIAGNOSTICS_REQUEST"):
            Path(request).write_text(
                json.dumps(
                    {
                        "repo": event.repo,
                        "sha": event.sha,
                        "pr": event.pr_number,
                        "event_at": event.event_at,
                        "github_run": int(env["GITHUB_RUN_ID"]),
                        "github_attempt": int(env["GITHUB_RUN_ATTEMPT"]),
                        "workflow": CheckRun(0, "", result.details_url).depot_workflow,
                        "root_check_id": result.root_check_id,
                        "check_id": result.check_id,
                    }
                )
            )
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
