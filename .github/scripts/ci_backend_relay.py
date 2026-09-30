#!/usr/bin/env python3
"""Hand one pull request event to one Depot CI workflow, and relay that workflow's gate.

Depot starts a workflow for every pull request event, and two events in the same second share
every name that carries the event. So the relay names the workflow: it takes the newest
`Depot run started` check of this event, posts a hand-off check that names its workflow id,
and reads the checks of that workflow only, matched by the id in each check's details URL.
Depot's wait job runs the tests only in the workflow a hand-off names. See "Finding one
event's Depot run" in .agents/skills/depot-ci/references/posthog-check-run-semantics.md.

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

from ci_backend_depot_failures import explain

DEPOT_APP_ID = 219785
DEPOT_ORG = "ntsdt08fpt"
# The PostHog tests GitHub App. Depot's wait and gate jobs post the same checks with it, because
# Depot posts its own checks from a budget that runs out at peak and then delivers them late.
MIRROR_APP_ID = 2492437
DEPOT_WORKFLOW = "Backend CI on Depot"
WAIT_JOB = "Wait for GitHub Actions to hand off backend tests"
# The first step of Depot's wait job posts this check; .depot/workflows/ci-backend.yml builds the same name.
STARTED_JOB = "Depot run started"
# Depot's wait job runs the tests only after a check of this name, for its own workflow id.
NAMED_HANDOFF = "Hand off backend tests to Depot workflow {workflow}"
# Renders the same text as the wait job's name expression in .depot/workflows/ci-backend.yml.
EVENT_SUFFIX = " (PR {pr}, event {event_at})"
# How a pull request event payload renders `updated_at`.
EVENT_TIME = "%Y-%m-%dT%H:%M:%SZ"
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


def event_check_name(job: str, pr_number: int, event_at: str) -> str:
    return f"{DEPOT_WORKFLOW} / {job}{EVENT_SUFFIX.format(pr=pr_number, event_at=event_at)}"


def wait_check_name(pr_number: int, event_at: str) -> str:
    return event_check_name(WAIT_JOB, pr_number, event_at)


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
        return Progress(Phase.CANCELLED, check.state, check.details_url)
    return Progress(Phase.FINISHED, check.state, check.details_url)


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


def post_handoff(
    repo: str,
    sha: str,
    token: str,
    workflow: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Post the check that lets Depot workflow `workflow` run this commit's tests, retrying transient failures."""
    body = {"name": NAMED_HANDOFF.format(workflow=workflow), "head_sha": sha, "status": "completed"}
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repo}/check-runs",
        data=json.dumps({**body, "conclusion": "success"}).encode(),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        },
    )
    for attempt in range(1, 4):
        try:
            with opener(request, timeout=30):
                return True
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            sys.stdout.write(f"::warning::Hand-off check not posted ({attempt}/3): {error}\n")
        sleep(5 * attempt)
    return False


def prerequisite_failure(reader: CheckReader, wait: CheckRun, current: Progress) -> Progress:
    for name in PREREQUISITES:
        latest = current_check(reader.read(f"{DEPOT_WORKFLOW} / {name}"), wait.depot_workflow)
        if latest and latest.state == "failure":
            return Progress(Phase.FINISHED, "failure", current.details_url, name, latest.id)
    return current


def poll(
    reader: CheckReader,
    event: Event,
    check_name: str,
    *,
    hand_off: Callable[[str], bool],
    deadline_minutes: int,
    absent_minutes: int,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Progress:
    """Hands the event to its newest started workflow, then polls until that workflow's check finishes.

    Depot can start late and posts the wait job's check only when that job ends, so a missing
    workflow or wait check gets `absent_minutes` before the relay gives up.
    """
    start = clock()
    started_name = event_check_name(STARTED_JOB, event.pr_number, event.event_at)
    event_name = wait_check_name(event.pr_number, event.event_at)
    workflow = None
    current = Progress(Phase.ABSENT)
    while True:
        try:
            if workflow is None and (started := reader.read(started_name)):
                newest = max(started, key=lambda check: check.id).depot_workflow
                if newest and hand_off(newest):
                    workflow = newest
                    sys.stdout.write(f"Handed the tests to Depot workflow {workflow}\n")
                else:
                    current = Progress(Phase.ABSENT, "hand-off not posted")
            if workflow:
                wait = current_check(reader.read(event_name), workflow)
                checks = reader.read(check_name) if wait and wait.state == "success" else []
                current = progress(wait, checks)
                # Depot cancels its own run only after a deterministic prerequisite failure. A gate that
                # failed without the cancel can follow a retryable one, so it keeps the retry options.
                if current.phase == Phase.CANCELLED and wait and wait.state == "success":
                    current = prerequisite_failure(reader, wait, current)
            sys.stdout.write(f"Depot run for this event: {current.phase.value} {current.state}".rstrip() + "\n")
            elapsed = clock() - start
            if current.phase in (Phase.FINISHED, Phase.DECLINED, Phase.CANCELLED):
                return current
            if current.phase == Phase.ABSENT and elapsed >= absent_minutes * 60:
                return current
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
            f"::error::Depot CI cancelled its run for this event of {event.sha}.",
            *retry_instructions(event, result.details_url, run_id),
        ]
    if result.phase == Phase.DECLINED:
        return 1, [f"::error::Depot declined the hand-off for {event.sha} (wait job: {result.state})"]
    if result.phase == Phase.ABSENT and result.state:
        return 1, [f"::error::The GitHub API refused the Depot hand-off for {event.sha}. Re-run this job."]
    if result.phase == Phase.ABSENT:
        return 1, [f"::error::Depot CI started no run for this event of {event.sha}"]
    return 1, [f"::error::No Depot verdict for {event.sha} within the relay's deadline"]


def main(argv: Sequence[str]) -> int:
    if argv[1:] != ["gate"]:
        sys.stderr.write("usage: ci_backend_relay.py gate\n")
        return 2
    env = os.environ
    event = Event(repo=env["REPO"], sha=env["SHA"], pr_number=int(env["PR_NUMBER"]), event_at=env["EVENT_AT"])
    reader = CheckRunReader(event.repo, event.sha, env["GH_TOKEN"], pr_number=event.pr_number)

    def hand_off(workflow: str) -> bool:
        return post_handoff(event.repo, event.sha, env["GH_TOKEN"], workflow)

    try:
        result = poll(reader, event, GATE_CHECK, hand_off=hand_off, deadline_minutes=90, absent_minutes=15)
    except ReadRefusedError as error:
        sys.stdout.write(f"::error::{error}\n")
        return 1
    code, lines = relay_gate(result, event, env.get("GITHUB_RUN_ID", ""))
    if code and result.phase == Phase.FINISHED and (match := DEPOT_RUN_URL.match(result.details_url)):
        lines += explain(*match.groups())
    sys.stdout.writelines(f"{line}\n" for line in lines)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
