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


def run(
    id: int,
    state: str,
    workflow: str = "live",
    started_at: str = "2026-09-24T09:56:00Z",
    prs: Sequence[int] = (PR,),
) -> Any:
    completed = state not in relay.PENDING_STATES
    return relay.CheckRun.from_api(
        {
            "id": id,
            "status": "completed" if completed else state,
            "conclusion": state if completed else None,
            "started_at": started_at,
            "pull_requests": [{"number": number} for number in prs],
            "details_url": f"https://depot.dev/orgs/org1/workflows/{workflow}?job=j1&repo=PostHog%2Fposthog",
        }
    )


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
            [run(1, "success", prs=())],
            [run(10, "success", prs=())],
            (relay.Phase.FINISHED, "success"),
            id="checks that list no pull request",
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
        return self._polls[min(self.poll, len(self._polls)) - 1].get(name, [])


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
    "checks,decision",
    [
        ([run(1, "success"), run(2, "skipped")], True),
        ([run(1, "skipped")], False),
        ([run(1, "cancelled"), run(2, "success", prs=(PR + 1,))], None),
    ],
)
def test_handoff_decision_matches_the_router(checks: list[Any], decision: bool | None) -> None:
    assert relay.handoff_decision(checks, PR) is decision


def test_report_requires_a_confirmed_handoff_before_waiting_for_depot() -> None:
    clock = FakeClock()
    reader = FakeReader(
        [{relay.HANDOFF_CHECK: [run(1, "queued")]}] * 2 + [{relay.HANDOFF_CHECK: [run(1, "success")]}],
        advance_on=relay.HANDOFF_CHECK,
    )
    assert relay.wait_for_handoff(reader, EVENT, clock=clock, sleep=clock.sleep)
    assert clock.now == 40


def test_report_fails_when_handoff_cannot_be_read() -> None:
    clock = FakeClock()
    reader = FakeReader([{}], advance_on=relay.HANDOFF_CHECK)
    with pytest.raises(relay.HandoffUnresolvedError):
        relay.wait_for_handoff(reader, EVENT, clock=clock, sleep=clock.sleep)
    assert clock.now == 10 * 60


def test_report_waits_past_ten_minutes_after_handoff() -> None:
    clock = FakeClock()
    reader = FakeReader(
        [{}] * 23
        + [
            {
                EVENT_WAIT: [run(1, "success")],
                relay.MIGRATION_CHECK: [run(2, "success")],
            }
        ]
    )
    result = relay.poll(
        reader, EVENT, relay.MIGRATION_CHECK, deadline_minutes=70, absent_minutes=70, clock=clock, sleep=clock.sleep
    )
    assert (result.phase, result.state) == (relay.Phase.FINISHED, "success")
    assert clock.now > 10 * 60


def test_migration_report_stops_when_depot_did_not_receive_the_handoff() -> None:
    clock = FakeClock()
    result = relay.poll(
        FakeReader(
            [
                {
                    EVENT_WAIT: [run(1, "success")],
                    relay.CHANGES_CHECK: [run(2, "skipped")],
                }
            ]
        ),
        EVENT,
        relay.MIGRATION_CHECK,
        deadline_minutes=70,
        absent_minutes=10,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result.phase == relay.Phase.DECLINED
    assert relay.report_migrations(result)[0] == 0
    assert clock.now == 0


@pytest.mark.parametrize(
    "late_poll,workflow",
    [
        pytest.param(
            {
                EVENT_WAIT: [run(1, "cancelled"), run(2, "success", workflow="replacement")],
                relay.MIGRATION_CHECK: [run(3, "success", workflow="replacement")],
            },
            "replacement",
            id="a late replacement of this event's run",
        ),
        pytest.param(
            {
                EVENT_WAIT: [run(1, "cancelled")],
                OLDER_RACING_WAIT: [run(2, "success", workflow="racing")],
                relay.MIGRATION_CHECK: [run(3, "success", workflow="racing")],
            },
            "racing",
            id="a racing event's run at the deadline",
        ),
    ],
)
def test_migration_report_finds_the_run_that_stands_in_for_a_cancelled_one(
    late_poll: dict[str, list[Any]], workflow: str
) -> None:
    clock = FakeClock()
    result = relay.poll(
        FakeReader([{EVENT_WAIT: [run(1, "cancelled")]}] * 25 + [late_poll]),
        EVENT,
        relay.MIGRATION_CHECK,
        deadline_minutes=70,
        absent_minutes=70,
        clock=clock,
        sleep=clock.sleep,
    )
    assert relay.report_migrations(result)[2] == {"migration_state": "success", "workflow_id": workflow}
    assert clock.now > 10 * 60


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
    code, lines = relay.relay_gate(result, EVENT, "123")
    assert code == exit_code
    if first_line is None:
        assert lines == []
    else:
        assert first_line in lines[0]


def test_relay_gate_names_the_failed_depot_run_to_retry() -> None:
    _, lines = relay.relay_gate(
        relay.Progress(relay.Phase.FINISHED, "failure", "https://depot.dev/orgs/o1/workflows/w1?job=j"), EVENT, "123"
    )
    assert "  depot ci retry <run ID> --org o1 --workflow w1 --failed" in lines
    assert "  gh run rerun 123 --repo PostHog/posthog --failed   # relays the new Depot result" in lines


@pytest.mark.parametrize(
    "result,exit_code,outputs",
    [
        (
            relay.Progress(relay.Phase.FINISHED, "failure", "https://depot.dev/orgs/o/workflows/w1?job=j"),
            0,
            {"migration_state": "failure", "workflow_id": "w1"},
        ),
        (relay.Progress(relay.Phase.FINISHED, "success", "https://example.com/not-depot"), 1, {}),
        (relay.Progress(relay.Phase.FINISHED, "skipped"), 0, {}),
        (relay.Progress(relay.Phase.CANCELLED, "cancelled"), 0, {}),
        (relay.Progress(relay.Phase.ABSENT), 1, {}),
        (relay.Progress(relay.Phase.FINISHED, "timed_out"), 1, {}),
        (relay.Progress(relay.Phase.RUNNING), 1, {}),
    ],
)
def test_report_migrations(result: Any, exit_code: int, outputs: dict[str, str]) -> None:
    code, _, written = relay.report_migrations(result)
    assert (code, written) == (exit_code, outputs)


class FakeResponse:
    def __init__(self, body: bytes, etag: str) -> None:
        self.status = 200
        self.headers = {"ETag": etag}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_handoff_reader_uses_the_github_actions_app() -> None:
    requested: list[str] = []

    def opener(request: Any, timeout: int) -> FakeResponse:
        requested.append(request.full_url)
        return FakeResponse(
            b'{"check_runs":[{"id":1,"status":"completed","conclusion":"success",'
            b'"pull_requests":[{"number":105723}]}]}',
            '"e1"',
        )

    reader = relay.CheckRunReader(
        "PostHog/posthog", EVENT.sha, "token", opener=opener, app_id=relay.GITHUB_ACTIONS_APP_ID
    )
    assert relay.handoff_decision(reader.read(relay.HANDOFF_CHECK), PR) is True
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(requested[0]).query)["app_id"] == [
        str(relay.GITHUB_ACTIONS_APP_ID)
    ]


def test_reader_reuses_its_answer_on_304_and_stops_on_repeated_refusals() -> None:
    sent: list[dict[str, str]] = []
    answers: list[Any] = [
        FakeResponse(b'{"check_runs": [{"id": 1, "status": "completed", "conclusion": "success"}]}', '"e1"'),
        urllib.error.HTTPError("url", 304, "Not Modified", {}, None),  # type: ignore[arg-type]
        *[urllib.error.HTTPError("url", 403, "Forbidden", {}, None) for _ in range(relay.MAX_REFUSALS)],  # type: ignore[arg-type]
    ]

    def opener(request: Any, timeout: int) -> Any:
        sent.append(dict(request.header_items()))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    reader = relay.CheckRunReader("PostHog/posthog", "abc", "token", opener=opener)
    assert [check.state for check in reader.read(relay.GATE_CHECK)] == ["success"]
    assert [check.state for check in reader.read(relay.GATE_CHECK)] == ["success"]
    assert sent[1]["If-none-match"] == '"e1"'
    for _ in range(relay.MAX_REFUSALS - 1):
        reader.read(relay.GATE_CHECK)
    with pytest.raises(relay.ReadRefusedError):
        reader.read(relay.GATE_CHECK)


@pytest.mark.parametrize("page", [1, 2])
@pytest.mark.parametrize(
    "error",
    [ConnectionResetError("reset"), http.client.IncompleteRead(b""), ValueError("invalid JSON")],
)
def test_reader_retries_interrupted_pages_without_reusing_a_stale_verdict(page: int, error: Exception) -> None:
    payload = {"id": 1, "status": "completed", "conclusion": "success"}
    answers: list[Any] = [FakeResponse(json.dumps({"check_runs": [payload]}).encode(), '"e1"')]
    if page == 2:
        answers.append(FakeResponse(json.dumps({"check_runs": [payload] * relay.PAGE_SIZE}).encode(), '"e2"'))
    answers += [error, FakeResponse(b'{"check_runs": []}', '"e3"')]

    def opener(request: Any, timeout: int) -> FakeResponse:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    reader = relay.CheckRunReader("PostHog/posthog", "abc", "token", opener=opener)
    assert reader.read(relay.GATE_CHECK)[0].state == "success"
    assert reader.read(relay.GATE_CHECK) == []
    assert reader.read(relay.GATE_CHECK) == []
    assert not answers
