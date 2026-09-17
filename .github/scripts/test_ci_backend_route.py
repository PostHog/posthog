import json
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("ci_backend_route.py")
SPEC = importlib.util.spec_from_file_location("ci_backend_route", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
route = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route)


def pr(
    percent: int = 25, number: int | None = 124, labels: Sequence[str] = (), fork: bool = False, draft: bool = False
) -> Any:
    return route.decide("pull_request", percent, number, list(labels), fork, draft)


@pytest.mark.parametrize(
    "number,percent,expected",
    [(124, 25, "depot"), (125, 25, "github"), (100, 0, "github"), (199, 100, "depot"), (0, 1, "depot")],
)
def test_bucket_is_pr_number_mod_100(number: int, percent: int, expected: str) -> None:
    assert pr(number=number, percent=percent).engine == expected


@pytest.mark.parametrize(
    "labels,fork,draft,expected",
    [
        (["ci-backend-github"], False, False, "github"),
        (["ci-backend-depot"], False, False, "depot"),
        (["ci-backend-depot", "ci-backend-github"], False, False, "github"),
        (["ci-backend-depot"], True, False, "github"),
        (["ci-backend-depot", "no-ci"], False, True, "github"),
        (["no-ci"], False, False, "depot"),
    ],
)
def test_overrides(labels: list[str], fork: bool, draft: bool, expected: str) -> None:
    assert pr(labels=labels, fork=fork, draft=draft).engine == expected


@pytest.mark.parametrize("event", ["workflow_dispatch", "push", "schedule", "merge_group"])
def test_non_pull_request_events_stay_on_github(event: str) -> None:
    assert route.decide(event, 100, None, ["ci-backend-depot"], False, False, "success").engine == "github"


def test_missing_pr_number_stays_on_github() -> None:
    assert pr(number=None, percent=100).engine == "github"


@pytest.mark.parametrize(
    "prior,labels,percent,expected",
    [
        ("success", ["ci-backend-github"], 0, "depot"),
        ("skipped", ["ci-backend-depot"], 100, "github"),
        ("cancelled", ["ci-backend-depot"], 0, "depot"),
        (None, [], 100, "depot"),
    ],
)
def test_earlier_run_of_the_commit_wins(prior: str | None, labels: list[str], percent: int, expected: str) -> None:
    assert route.decide("pull_request", percent, 124, labels, False, False, prior).engine == expected


def check(run_id: int, status: str, conclusion: str | None, pr_number: int = 124) -> dict[str, Any]:
    return {"id": run_id, "status": status, "conclusion": conclusion, "pull_requests": [{"number": pr_number}]}


@pytest.mark.parametrize(
    "check_runs,expected",
    [
        ([check(1, "completed", "success"), check(2, "queued", None)], "success"),
        ([check(1, "completed", "success"), check(2, "completed", "skipped")], "skipped"),
        ([check(1, "completed", "success", pr_number=125)], None),
        ([{"id": 1, "status": "completed", "conclusion": "success", "pull_requests": []}], None),
        ([], None),
    ],
)
def test_handoff_conclusion_is_the_newest_concluded_for_this_pull_request(
    check_runs: list[dict[str, Any]], expected: str | None
) -> None:
    assert route.handoff_conclusion(check_runs, 124) == expected


def test_read_prior_handoff_fails_closed_after_three_failed_reads() -> None:
    calls: list[int] = []

    def failing() -> list[dict[str, Any]]:
        calls.append(1)
        raise OSError("boom")

    with pytest.raises(RuntimeError):
        route.read_prior_handoff(failing, 124, pause_seconds=0)
    assert len(calls) == 3


def test_read_prior_handoff_recovers_from_one_failed_read() -> None:
    answers: list[Any] = [OSError("boom"), [check(1, "completed", "success")]]

    def flaky() -> list[dict[str, Any]]:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert route.read_prior_handoff(flaky, 124, pause_seconds=0) == "success"


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 0), ("", 0), ("abc", 0), ("-5", 0), ("42", 42), ("250", 100), (" 7 ", 7), ("²", 0), ("9" * 5000, 0)],
)
def test_parse_percent_fails_closed(raw: str | None, expected: int) -> None:
    assert route.parse_percent(raw) == expected


@pytest.mark.parametrize("labels", [json.dumps(["other"]), "null", ""])
def test_main_writes_outputs(labels: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PERCENT", "50")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", labels)
    monkeypatch.setattr(route, "fetch_handoff_checks", lambda repo, sha, token: [])
    monkeypatch.setenv("REPO", "PostHog/posthog")
    monkeypatch.setenv("SHA", "abc")
    monkeypatch.setenv("GH_TOKEN", "t")
    assert route.main() == 0
    assert output.read_text() == "engine=depot\nreason=bucket 7 < 50%\n"


def test_main_fails_when_the_earlier_handoff_cannot_be_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
        raise OSError("boom")

    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", "[]")
    monkeypatch.setenv("REPO", "PostHog/posthog")
    monkeypatch.setenv("SHA", "abc")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(route, "fetch_handoff_checks", failing)
    monkeypatch.setattr(route.time, "sleep", lambda seconds: None)
    assert route.main() == 1
    assert not (tmp_path / "out").exists()
