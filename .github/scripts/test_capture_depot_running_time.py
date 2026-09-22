import urllib.error
import importlib.util
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("capture_depot_running_time.py")
SPEC = importlib.util.spec_from_file_location("capture_depot_running_time", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)

GATE = "Django Tests Pass on Depot"
CONTEXT = capture.github_context(
    {
        "GITHUB_REPOSITORY": "PostHog/posthog",
        "GITHUB_RUN_ID": "323428565134500",
        "GITHUB_RUN_NUMBER": "7",
    }
)


def check_run(
    id: int, workflow: str, job: str, started: str, completed: str | None = None, conclusion: str = "success"
) -> dict[str, Any]:
    return {
        "id": id,
        "name": f"Backend CI on Depot / {job}",
        "status": "completed" if completed else "in_progress",
        "conclusion": conclusion if completed else None,
        "started_at": started,
        "completed_at": completed,
        "details_url": f"https://depot.dev/orgs/org1/workflows/{workflow}?job=j{id}&repo=PostHog%2Fposthog",
    }


def test_builds_run_and_job_events_from_this_workflow_only() -> None:
    check_runs = [
        check_run(
            1,
            "older",
            "Wait for GitHub Actions to hand off backend tests",
            "2026-09-18T14:00:00Z",
            "2026-09-18T14:01:00Z",
        ),
        check_run(
            2,
            "wf1",
            "Wait for GitHub Actions to hand off backend tests",
            "2026-09-18T15:00:00Z",
            "2026-09-18T15:02:00Z",
        ),
        check_run(3, "wf1", "Django tests (1/2)", "2026-09-18T15:03:00Z", "2026-09-18T15:10:00Z", "failure"),
        check_run(4, "wf1", "Django tests (1/2)", "2026-09-18T15:11:00Z", "2026-09-18T15:20:30Z"),
        check_run(5, "wf1", "Django tests (2/2)", "2026-09-18T15:03:00Z"),
        check_run(6, "wf1", GATE, "2026-09-18T15:29:00Z", "2026-09-18T15:30:00Z", "failure"),
        check_run(7, "wf1", "Validate migrations", "2026-09-18T15:02:05Z", "2026-09-18T15:02:04Z", "skipped"),
        check_run(8, "other", GATE, "2026-09-18T15:31:00Z", "2026-09-18T15:31:01Z"),
    ]

    events = capture.build_events(check_runs, "wf1", GATE, CONTEXT, 1)

    run_event, group_event, *job_events = events
    assert run_event["timestamp"] == "2026-09-18T15:30:00+00:00"
    assert run_event["properties"] == {
        "duration_seconds": 1800,
        "url": "https://depot.dev/orgs/org1/workflows/wf1",
        "attempt": 1,
        "started_at": "2026-09-18T15:00:00Z",
        "conclusion": "failure",
        "runner": "depot",
        "ci_engine": "depot",
        "depot_workflow_id": "wf1",
        **CONTEXT,
        "$groups": {"workflow_run": "PostHog/posthog/323428565134500"},
    }
    assert group_event["properties"]["$group_set"] == {"conclusion": "failure"}
    assert [
        (e["event"], e["properties"]["name"], e["properties"]["duration_seconds"], e["properties"]["conclusion"])
        for e in job_events
    ] == [
        ("posthog-ci-running-time-job", "Wait for GitHub Actions to hand off backend tests", 120, "success"),
        ("posthog-ci-running-time-job", "Django tests (1/2)", 570, "success"),
        ("posthog-ci-running-time-job", GATE, 60, "failure"),
        ("posthog-ci-running-time-job", "Validate migrations", 0, "skipped"),
    ]


def test_clamps_workflow_duration_when_the_gate_completes_before_it_starts() -> None:
    events = capture.build_events(
        [check_run(1, "wf1", GATE, "2026-09-18T15:31:00Z", "2026-09-18T15:30:00Z")], "wf1", GATE, CONTEXT, 1
    )

    assert events[0]["properties"]["duration_seconds"] == 0


@pytest.mark.parametrize(
    "check_runs",
    [
        [check_run(1, "wf1", GATE, "2026-09-18T15:29:00Z")],
        [check_run(1, "other", GATE, "2026-09-18T15:29:00Z", "2026-09-18T15:29:30Z")],
    ],
    ids=["gate still running", "gate only in another workflow"],
)
def test_sends_nothing_without_a_completed_gate(check_runs: list[dict[str, Any]]) -> None:
    assert capture.build_events(check_runs, "wf1", GATE, CONTEXT, 1) == []


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.github.com", code, "error", Message(), None)


GATE_RUN = [check_run(1, "wf1", GATE, "2026-09-18T15:29:00Z", "2026-09-18T15:30:00Z")]


@pytest.mark.parametrize(
    "reads, batches_sent",
    [
        ([[], [], GATE_RUN], 1),
        ([http_error(502), GATE_RUN], 1),
        ([http_error(403)], 0),
        ([[], [], []], 0),
    ],
    ids=["gate completed late", "server error", "client error", "gate never completed"],
)
def test_retries_the_check_run_lookup(
    monkeypatch: pytest.MonkeyPatch, reads: list[list[dict[str, Any]] | Exception], batches_sent: int
) -> None:
    pending = iter(reads)
    sent: list[list[dict[str, Any]]] = []

    def fetch_check_runs(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
        read = next(pending)
        if isinstance(read, Exception):
            raise read
        return read

    monkeypatch.setattr(capture, "fetch_check_runs", fetch_check_runs)
    monkeypatch.setattr(capture, "capture", lambda token, events: sent.append(events))
    monkeypatch.setattr(capture, "LOOKUP_BACKOFF_SECONDS", 0)
    monkeypatch.setenv("POSTHOG_API_TOKEN", "phc_test")
    monkeypatch.delenv("POSTHOG_DEVEX_PROJECT_API_TOKEN", raising=False)
    monkeypatch.setenv("DEPOT_WORKFLOW_ID", "wf1")

    assert capture.main() == 0
    assert next(pending, None) is None
    assert len(sent) == batches_sent
