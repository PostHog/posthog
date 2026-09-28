import re
import json
import http.client
import urllib.error
import urllib.parse
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import yaml

SCRIPT_PATH = Path(__file__).with_name("ci_backend_relay.py")
SPEC = importlib.util.spec_from_file_location("ci_backend_relay", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)

DEPOT_WORKFLOW_FILE = Path(__file__).parents[2] / ".depot" / "workflows" / "ci-backend.yml"
PR = 105723
EVENT_AT = "2026-09-24T09:54:20Z"
EVENT = relay.Event(repo="PostHog/posthog", sha="a8a3755cf964", pr_number=PR, event_at=EVENT_AT)
EVENT_WAIT = relay.wait_check_name(PR, EVENT_AT)
PLAIN_WAIT = f"{relay.DEPOT_WORKFLOW} / {relay.WAIT_JOB}"
OLDER_RACING_WAIT = relay.wait_check_name(PR, "2026-09-24T09:54:19Z")
NEWER_RACING_WAIT = relay.wait_check_name(PR, "2026-09-24T09:54:22Z")


def api_run(id: int, state: str, workflow: str = "live", attempt: str = "") -> dict[str, Any]:
    completed = state not in relay.PENDING_STATES
    query = f"job=j1&attempt={attempt}" if attempt else "job=j1&repo=PostHog%2Fposthog"
    return {
        "id": id,
        "status": "completed" if completed else state,
        "conclusion": state if completed else None,
        "app": {"id": relay.MIRROR_APP_ID if attempt else relay.DEPOT_APP_ID},
        "details_url": f"https://depot.dev/orgs/ntsdt08fpt/workflows/{workflow}?{query}",
    }


def run(id: int, state: str, workflow: str = "live", started_at: str = "2026-09-24T09:56:00Z") -> Any:
    return relay.CheckRun.from_api({**api_run(id, state, workflow), "started_at": started_at})


def test_wait_job_name_matches_the_depot_workflow() -> None:
    text = DEPOT_WORKFLOW_FILE.read_text()
    job = text[text.index("\n    wait-for-handoff:") :]
    name = re.search(r"\n        name: (.+)\n", job)
    assert name is not None
    expected = (
        relay.WAIT_JOB
        + "${{ github.event_name == 'pull_request' && format('"
        + relay.EVENT_SUFFIX.replace("{pr}", "{0}").replace("{event_at}", "{1}")
        + "', github.event.pull_request.number, github.event.pull_request.updated_at) || '' }}"
    )
    assert name.group(1) == expected


def test_mirrored_checks_carry_the_names_the_relay_reads() -> None:
    jobs = yaml.safe_load(DEPOT_WORKFLOW_FILE.read_text())["jobs"]
    steps = [step for job in jobs.values() for step in job.get("steps", [])]
    handoff = next(step for step in steps if step.get("name") == "Post the hand-off checks for the relay")
    gate = next(step for step in steps if step.get("name") == "Post the gate check for the relay")
    wait_check = (
        handoff["env"]["WAIT_CHECK"]
        .replace("${{ github.event.pull_request.number }}", str(PR))
        .replace("${{ github.event.pull_request.updated_at }}", EVENT_AT)
    )
    assert wait_check == EVENT_WAIT
    assert handoff["env"]["GATE_CHECK"] == gate["env"]["GATE_CHECK"] == relay.GATE_CHECK


@pytest.mark.parametrize(
    "event_waits,gates,expected",
    [
        pytest.param([], [], (relay.Phase.ABSENT, ""), id="no run yet"),
        pytest.param([run(1, "in_progress")], [], (relay.Phase.STARTING, "in_progress"), id="waiting for hand-off"),
        pytest.param([run(1, "failure")], [], (relay.Phase.DECLINED, "failure"), id="depot declined"),
        pytest.param([run(1, "cancelled")], [], (relay.Phase.CANCELLED, "cancelled"), id="run cancelled"),
        pytest.param(
            [run(1, "success")],
            [run(9, "cancelled", workflow="stale", started_at="2026-09-24T09:55:14Z")],
            (relay.Phase.RUNNING, ""),
            id="superseded run's cancelled gate is ignored",
        ),
        pytest.param(
            [run(1, "success")],
            [run(9, "cancelled", workflow="stale"), run(10, "success")],
            (relay.Phase.FINISHED, "success"),
            id="this run's gate wins over a newer id elsewhere",
        ),
        pytest.param(
            [run(1, "cancelled", workflow="dup1"), run(2, "success", workflow="dup2")],
            [run(10, "failure", workflow="dup2")],
            (relay.Phase.FINISHED, "failure"),
            id="duplicate run of the event replaces a cancelled one",
        ),
        pytest.param(
            [run(1, "success")],
            [run(10, "cancelled")],
            (relay.Phase.CANCELLED, "cancelled"),
            id="this run cancelled after the hand-off",
        ),
        pytest.param(
            [run(1, "success")],
            [run(10, "failure"), run(11, "success")],
            (relay.Phase.FINISHED, "success"),
            id="retried gate",
        ),
    ],
)
def test_progress_of_this_events_run(event_waits: list[Any], gates: list[Any], expected: tuple[Any, str]) -> None:
    wait = relay.newest_live(event_waits)
    result = relay.progress(wait, gates)
    assert (result.phase, result.state) == expected


class FakeReader:
    def __init__(self, polls: Sequence[dict[str, list[Any]]], advance_on: str = EVENT_WAIT) -> None:
        self._polls = list(polls)
        self._advance_on = advance_on
        self.poll = 0
        self.reads: list[str] = []

    def read(self, name: str) -> list[Any]:
        self.reads.append(name)
        if name == self._advance_on:
            self.poll += 1
        answer = self._polls[min(self.poll, len(self._polls)) - 1].get(name, [])
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(
    "polls,expected,min_minutes",
    [
        pytest.param(
            [{EVENT_WAIT: [run(1, "cancelled", workflow="dup1")]}] * 3
            + [{EVENT_WAIT: [run(1, "cancelled", workflow="dup1"), run(2, "success", workflow="dup2")]}]
            + [
                {
                    EVENT_WAIT: [run(1, "cancelled", workflow="dup1"), run(2, "success", workflow="dup2")],
                    relay.GATE_CHECK: [run(10, "success", workflow="dup2")],
                }
            ],
            (relay.Phase.FINISHED, "success"),
            0,
            id="a cancelled run is replaced within the grace window",
        ),
        pytest.param(
            [{EVENT_WAIT: [run(1, "cancelled")]}],
            (relay.Phase.CANCELLED, "cancelled"),
            15,
            id="a cancelled run fails only after the grace window",
        ),
        pytest.param([{}], (relay.Phase.ABSENT, ""), 15, id="no run fails after the grace window"),
        pytest.param(
            [{EVENT_WAIT: [run(1, "success")]}] * 16
            + [{EVENT_WAIT: relay.ReadFailedError("Cannot read")}]
            + [{EVENT_WAIT: [run(1, "success")], relay.GATE_CHECK: [run(10, "success")]}],
            (relay.Phase.FINISHED, "success"),
            16,
            id="a failed read after the grace window keeps waiting",
        ),
        pytest.param(
            [
                {
                    OLDER_RACING_WAIT: [run(1, "success", workflow="racing")],
                    relay.GATE_CHECK: [run(10, "failure", workflow="racing")],
                }
            ],
            (relay.Phase.FINISHED, "failure"),
            15,
            id="an older racing event's run stands in for an absent run",
        ),
        pytest.param(
            [
                {
                    EVENT_WAIT: [run(1, "cancelled")],
                    NEWER_RACING_WAIT: [run(2, "success", workflow="racing")],
                    relay.GATE_CHECK: [run(10, "success", workflow="racing")],
                }
            ],
            (relay.Phase.FINISHED, "success"),
            15,
            id="a newer racing event's run stands in for a cancelled run",
        ),
        pytest.param(
            [
                {
                    NEWER_RACING_WAIT: [run(1, "success", workflow="newer")],
                    OLDER_RACING_WAIT: [run(2, "success", workflow="older")],
                    relay.GATE_CHECK: [run(10, "cancelled", workflow="newer"), run(11, "success", workflow="older")],
                }
            ],
            (relay.Phase.FINISHED, "success"),
            15,
            id="the next racing event's run stands in when the followed one is cancelled",
        ),
        pytest.param(
            [
                {
                    NEWER_RACING_WAIT: [run(1, "success", workflow="newer")],
                    OLDER_RACING_WAIT: [run(2, "success", workflow="older")],
                    relay.GATE_CHECK: [run(10, "success", workflow="newer"), run(11, "failure", workflow="older")],
                }
            ],
            (relay.Phase.FINISHED, "success"),
            15,
            id="the newer of two racing runs stands in",
        ),
        pytest.param(
            [
                {
                    NEWER_RACING_WAIT: [run(1, "skipped", workflow="declined")],
                    OLDER_RACING_WAIT: [run(2, "success", workflow="older")],
                    relay.GATE_CHECK: [run(10, "success", workflow="older")],
                }
            ],
            (relay.Phase.FINISHED, "success"),
            15,
            id="a racing run that declined the hand-off does not stand in",
        ),
        pytest.param(
            [
                {
                    relay.wait_check_name(PR, "2026-09-24T09:54:17Z"): [run(1, "success", workflow="earlier")],
                    relay.GATE_CHECK: [run(10, "success", workflow="earlier")],
                }
            ],
            (relay.Phase.ABSENT, ""),
            15,
            id="an event outside the race window does not stand in",
        ),
        pytest.param(
            [{EVENT_WAIT: [run(1, "success")]}],
            (relay.Phase.RUNNING, ""),
            90,
            id="a running gate hits the overall deadline",
        ),
    ],
)
def test_poll_waits_out_a_replacement_before_failing(
    polls: list[dict[str, list[Any]]], expected: tuple[Any, str], min_minutes: int
) -> None:
    clock = FakeClock()
    result = relay.poll(
        FakeReader(polls),
        EVENT,
        relay.GATE_CHECK,
        deadline_minutes=90,
        absent_minutes=15,
        clock=clock,
        sleep=clock.sleep,
    )
    assert (result.phase, result.state) == expected
    assert clock.now >= min_minutes * 60


def test_poll_does_not_use_an_ambiguous_plain_named_wait() -> None:
    clock = FakeClock()
    reader = FakeReader([{PLAIN_WAIT: [run(1, "success")], relay.GATE_CHECK: [run(2, "success")]}])
    result = relay.poll(
        reader, EVENT, relay.GATE_CHECK, deadline_minutes=90, absent_minutes=15, clock=clock, sleep=clock.sleep
    )
    assert result.phase == relay.Phase.ABSENT
    assert PLAIN_WAIT not in reader.reads


@pytest.mark.parametrize(
    "result,exit_code,first_line",
    [
        (relay.Progress(relay.Phase.FINISHED, "success"), 0, None),
        (
            relay.Progress(relay.Phase.FINISHED, "failure", "https://depot.dev/orgs/o/workflows/w1?job=j"),
            1,
            "concluded failure",
        ),
        (relay.Progress(relay.Phase.CANCELLED, "cancelled"), 1, "cancelled its run"),
        (relay.Progress(relay.Phase.DECLINED, "failure"), 1, "declined the hand-off"),
        (relay.Progress(relay.Phase.ABSENT), 1, "started no run"),
        (relay.Progress(relay.Phase.RUNNING), 1, "No Depot verdict"),
    ],
)
def test_relay_gate_fails_closed(result: Any, exit_code: int, first_line: str | None) -> None:
    code, lines = relay.relay_gate(result, EVENT)
    assert code == exit_code
    if first_line is None:
        assert lines == []
    else:
        assert first_line in lines[0]


def test_relay_gate_names_the_failed_depot_run_to_retry() -> None:
    _, lines = relay.relay_gate(
        relay.Progress(relay.Phase.FINISHED, "failure", "https://depot.dev/orgs/o1/workflows/w1?job=j"), EVENT
    )
    assert any("push a new commit" in line for line in lines)
    assert any("routing rules choose the engine" in line for line in lines)
    assert not any("ci-backend-github" in line for line in lines)


def api_check() -> dict[str, Any]:
    return {
        "id": 1,
        "status": "completed",
        "conclusion": "success",
        "app": {"id": relay.DEPOT_APP_ID},
        "name": relay.GATE_CHECK,
        "head_sha": "abc",
        "pull_requests": [{"number": PR}],
        "details_url": "https://depot.dev/orgs/ntsdt08fpt/workflows/live?job=j1&repo=PostHog%2Fposthog",
    }


class FakeResponse:
    def __init__(self, body: bytes, etag: str) -> None:
        self.status = 200
        self.headers = {"ETag": etag}
        self._body = body

    def read(self, limit: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_reader_reuses_its_answer_on_304_and_stops_on_repeated_refusals() -> None:
    sent: list[dict[str, str]] = []
    answers: list[Any] = [
        FakeResponse(json.dumps({"check_runs": [api_check()]}).encode(), '"e1"'),
        urllib.error.HTTPError("url", 304, "Not Modified", {}, None),  # type: ignore[arg-type]
        *[urllib.error.HTTPError("url", 403, "Forbidden", {}, None) for _ in range(relay.MAX_REFUSALS)],  # type: ignore[arg-type]
    ]

    def opener(request: Any, timeout: int) -> Any:
        sent.append(dict(request.header_items()))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    reader = relay.CheckRunReader("PostHog/posthog", "abc", "token", opener=opener, app_ids=(relay.DEPOT_APP_ID,))
    assert [check.state for check in reader.read(relay.GATE_CHECK)] == ["success"]
    assert [check.state for check in reader.read(relay.GATE_CHECK)] == ["success"]
    assert sent[1]["If-none-match"] == '"e1"'
    for _ in range(relay.MAX_REFUSALS - 1):
        with pytest.raises(relay.ReadFailedError):
            reader.read(relay.GATE_CHECK)
    with pytest.raises(relay.ReadRefusedError):
        reader.read(relay.GATE_CHECK)


@pytest.mark.parametrize("page", [1, 2])
@pytest.mark.parametrize(
    "error",
    [ConnectionResetError("reset"), http.client.IncompleteRead(b""), ValueError("invalid JSON")],
)
def test_reader_retries_interrupted_pages_without_reusing_a_stale_verdict(page: int, error: Exception) -> None:
    payload = api_check()
    answers: list[Any] = [FakeResponse(json.dumps({"check_runs": [payload]}).encode(), '"e1"')]
    if page == 2:
        answers.append(FakeResponse(json.dumps({"check_runs": [payload] * relay.PAGE_SIZE}).encode(), '"e2"'))
    answers += [error, FakeResponse(b'{"check_runs": []}', '"e3"')]

    def opener(request: Any, timeout: int) -> FakeResponse:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    reader = relay.CheckRunReader("PostHog/posthog", "abc", "token", opener=opener, app_ids=(relay.DEPOT_APP_ID,))
    assert reader.read(relay.GATE_CHECK)[0].state == "success"
    with pytest.raises(relay.ReadFailedError):
        reader.read(relay.GATE_CHECK)
    assert reader.read(relay.GATE_CHECK) == []
    assert not answers


@pytest.mark.parametrize("name", relay.PREREQUISITES)
@pytest.mark.parametrize(
    "state,workflow,newer",
    [
        ("failure", "live", None),
        ("failure", "other", None),
        ("success", "live", None),
        ("failure", "live", "pending"),
        ("failure", "live", "success"),
    ],
)
def test_cancelled_gate_reports_only_current_selected_prerequisite(
    name: str, state: str, workflow: str, newer: str | None
) -> None:
    roots = [run(2, state, workflow)]
    if newer:
        roots.append(run(3, newer, workflow))
    clock = FakeClock()
    result = relay.poll(
        FakeReader(
            [
                {
                    EVENT_WAIT: [run(1, "success")],
                    relay.GATE_CHECK: [run(5, "cancelled")],
                    f"{relay.DEPOT_WORKFLOW} / {name}": roots,
                }
            ]
        ),
        EVENT,
        relay.GATE_CHECK,
        deadline_minutes=90,
        absent_minutes=15,
        clock=clock,
        sleep=clock.sleep,
    )
    code, lines = relay.relay_gate(result, EVENT)
    assert code == 1
    if state == "failure" and workflow == "live" and newer is None:
        assert clock.now == 0
        assert lines == [f"::error::{name} failed on Depot (check 2). Push a fix; a retry will not help."]
        assert result.root_check_id == 2
    else:
        assert result.phase == relay.Phase.CANCELLED
        assert clock.now == 900


@pytest.mark.parametrize("name", relay.PREREQUISITES)
def test_failed_gate_keeps_retry_options_after_a_prerequisite_failure(name: str) -> None:
    # Without Depot's self-cancel, the prerequisite may have failed on a retryable setup step.
    clock = FakeClock()
    result = relay.poll(
        FakeReader(
            [
                {
                    EVENT_WAIT: [run(1, "success")],
                    relay.GATE_CHECK: [run(5, "failure")],
                    f"{relay.DEPOT_WORKFLOW} / {name}": [run(2, "failure")],
                }
            ]
        ),
        EVENT,
        relay.GATE_CHECK,
        deadline_minutes=90,
        absent_minutes=15,
        clock=clock,
        sleep=clock.sleep,
    )
    code, lines = relay.relay_gate(result, EVENT)
    assert code == 1
    assert not result.root_failure
    assert not any("a retry will not help" in line for line in lines)


@pytest.mark.parametrize(
    "field,value",
    [
        ("app", {"id": 99}),
        ("app", None),
        ("name", "other check"),
        ("head_sha", "other"),
        ("pull_requests", [{"number": PR + 1}]),
        ("details_url", "https://depot.dev/orgs/other/workflows/live"),
        ("details_url", "https://depot.dev.example.com/orgs/ntsdt08fpt/workflows/live"),
        ("details_url", "https://depot.dev@evil.example.com/orgs/ntsdt08fpt/workflows/live"),
        ("details_url", "http://depot.dev/orgs/ntsdt08fpt/workflows/live"),
    ],
)
def test_reader_rejects_wrong_identity(field: str, value: Any) -> None:
    payload = {**api_check(), field: value}
    reader = relay.CheckRunReader(
        "PostHog/posthog",
        "abc",
        "token",
        pr_number=PR,
        opener=lambda *a, **kw: FakeResponse(json.dumps({"check_runs": [payload]}).encode(), ""),
    )
    assert reader.read(relay.GATE_CHECK) == []


def test_reader_keeps_valid_checks_beside_a_malformed_one() -> None:
    answer = json.dumps({"check_runs": [{**api_check(), "app": None}, api_check()]}).encode()
    reader = relay.CheckRunReader(
        "PostHog/posthog", "abc", "token", pr_number=PR, opener=lambda *a, **kw: FakeResponse(answer, "")
    )
    assert len(reader.read(relay.GATE_CHECK)) == 1


@pytest.mark.parametrize(
    "mirror_gate,depot_gate,expected",
    [
        pytest.param(
            [(2, "failure", "w1", "a1"), (5, "success", "w1", "a2")],
            [],
            (relay.Phase.FINISHED, "success"),
            id="Depot's copies lag",
        ),
        pytest.param(
            [(2, "failure", "w1", "a1"), (5, "success", "w1", "a2")],
            [(9, "failure", "w1")],
            (relay.Phase.FINISHED, "success"),
            id="a late copy of an older attempt",
        ),
        pytest.param(
            [(2, "failure", "w1", "a1"), (5, "success", "w1", "a2")],
            [(8, "success", "w1"), (9, "failure", "w1")],
            (relay.Phase.FINISHED, "success"),
            id="late copies of both attempts",
        ),
        pytest.param(
            [(2, "failure", "w1", "a1"), (5, "failure", "w1", "a2")],
            [(4, "failure", "w1"), (9, "failure", "w1")],
            (relay.Phase.FINISHED, "failure"),
            id="a retry that failed again",
        ),
        pytest.param(
            [(2, "success", "w1", "a1")],
            [(4, "success", "w1"), (9, "failure", "w1")],
            (relay.Phase.FINISHED, "failure"),
            id="a newer attempt the mirror missed",
        ),
        pytest.param(
            [(2, "failure", "w1", "a1")],
            [(4, "failure", "w1"), (9, "in_progress", "w1")],
            (relay.Phase.RUNNING, "in_progress"),
            id="a running retry the mirror has not posted",
        ),
        pytest.param(
            [(5, "success", "w1", "a2")],
            [(4, "cancelled", "w1")],
            (relay.Phase.FINISHED, "success"),
            id="a replacement for a job cancelled before it started",
        ),
        pytest.param(
            [(5, "success", "w1", "a2")],
            [(4, "cancelled", "w1"), (9, "in_progress", "w1")],
            (relay.Phase.RUNNING, "in_progress"),
            id="a replacement Depot has not finished after a cancelled job",
        ),
        pytest.param(
            [(5, "success", "other", "a1")],
            [(9, "failure", "w1")],
            (relay.Phase.FINISHED, "failure"),
            id="another workflow's mirrored gate",
        ),
        pytest.param(
            [(5, "success", "other", "a1")],
            [],
            (relay.Phase.RUNNING, ""),
            id="only another workflow's mirrored gate",
        ),
        pytest.param([(5, "success", "w1", "a1")], None, None, id="Depot's app read fails"),
    ],
)
def test_relay_reads_the_current_attempt_across_apps(
    mirror_gate: list[tuple[int, str, str, str]],
    depot_gate: list[tuple[int, str, str]] | None,
    expected: tuple[Any, str] | None,
) -> None:
    mirror = {EVENT_WAIT: [api_run(1, "success", "w1", "w")], relay.GATE_CHECK: [api_run(*c) for c in mirror_gate]}
    depot = {
        EVENT_WAIT: [api_run(3, "success", "w1")],
        relay.GATE_CHECK: None if depot_gate is None else [api_run(*c) for c in depot_gate],
    }

    def opener(request: Any, timeout: int) -> FakeResponse:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        name, app_id = query["check_name"][0], int(query["app_id"][0])
        runs = (mirror if app_id == relay.MIRROR_APP_ID else depot)[name]
        if runs is None:
            raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)  # type: ignore[arg-type]
        body = [{**check, "name": name, "head_sha": EVENT.sha} for check in runs]
        return FakeResponse(json.dumps({"check_runs": body}).encode(), "")

    reader = relay.CheckRunReader(EVENT.repo, EVENT.sha, "token", opener=opener)
    wait = relay.newest_live(reader.read(EVENT_WAIT))
    if expected is None:
        with pytest.raises(relay.ReadFailedError):
            reader.read(relay.GATE_CHECK)
        return
    current = relay.progress(wait, reader.read(relay.GATE_CHECK))
    assert (current.phase, current.state) == expected
