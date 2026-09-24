import json
import urllib.error
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
    percent: int = 25, number: int | None = 125, labels: Sequence[str] = (), fork: bool = False, draft: bool = False
) -> Any:
    return route.decide("pull_request", percent, number, list(labels), fork, draft)


@pytest.mark.parametrize("number,bucket", [(0, 40), (7, 30), (124, 94), (125, 19), (103100, 33)])
def test_bucket_is_a_fixed_hash_of_the_pr_number(number: int, bucket: int) -> None:
    assert route.bucket_of(number) == bucket
    assert pr(number=number, percent=bucket).engine == "github"
    assert pr(number=number, percent=bucket + 1).engine == "depot"


def test_consecutive_prs_spread_across_buckets() -> None:
    routed = [pr(number=number, percent=5).engine == "depot" for number in range(100000, 101000)]
    assert 30 <= sum(routed) <= 70
    assert not any(all(routed[i : i + 5]) for i in range(len(routed) - 4))


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


def test_merge_queue_batches_stay_on_github() -> None:
    queued = route.decide("pull_request", 100, 124, ["ci-backend-depot"], False, True, "success", "trunk-merge/pr-1/x")
    assert queued.engine == "github"
    assert route.decide("pull_request", 100, 124, [], False, False, None, "feature/trunk-merge").engine == "depot"


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
        ([check(1, "completed", "success"), check(2, "completed", "cancelled")], "success"),
        ([check(1, "completed", "success"), check(2, "completed", "skipped")], "success"),
        ([check(1, "completed", "skipped"), check(2, "completed", "cancelled")], "skipped"),
        ([check(1, "completed", "cancelled"), check(2, "completed", "failure")], "failure"),
        ([check(1, "completed", "success", pr_number=125)], None),
        ([{"id": 1, "status": "completed", "conclusion": "success", "pull_requests": []}], None),
        ([], None),
    ],
)
def test_handoff_conclusion_keeps_the_engine_that_already_ran_this_pull_request(
    check_runs: list[dict[str, Any]], expected: str | None
) -> None:
    assert route.handoff_conclusion(check_runs, 124) == expected


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.github.com", code, "boom", {}, None)  # type: ignore[arg-type]


def opener_from(answers: list[Any]) -> Any:
    def opener(request: Any, timeout: int) -> Any:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    return opener


def test_fetch_retries_a_server_error_then_returns_the_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route.time, "sleep", lambda seconds: None)
    checks = [check(1, "completed", "success")]
    opener = opener_from([http_error(502), {"check_runs": checks}])
    assert route.fetch_handoff_checks("PostHog/posthog", "abc", "t", opener=opener) == checks


@pytest.mark.parametrize(
    "answers,attempts_used",
    [([http_error(403)], 1), ([http_error(503)] * 3, 3), ([urllib.error.URLError("down")] * 3, 3)],
)
def test_fetch_fails_closed_without_retrying_client_errors(
    answers: list[Exception], attempts_used: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(route.time, "sleep", lambda seconds: None)
    remaining = list(answers)
    with pytest.raises(route.HandoffReadError):
        route.fetch_handoff_checks("PostHog/posthog", "abc", "t", opener=opener_from(remaining))
    assert len(answers) - len(remaining) == attempts_used


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
    assert output.read_text() == "engine=depot\nreason=bucket 30 < 50%\n"


@pytest.mark.parametrize("percent", ["", "0", "5"])
def test_main_keeps_a_handed_off_commit_on_depot_after_rollback(
    percent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
        return [{"id": 1, "status": "completed", "conclusion": "success", "pull_requests": [{"number": 7}]}]

    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PERCENT", percent)
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", "[]")
    monkeypatch.setenv("REPO", "PostHog/posthog")
    monkeypatch.setenv("SHA", "abc")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(route, "fetch_handoff_checks", fetch)
    assert route.main() == 0
    assert output.read_text().startswith("engine=depot\n")


@pytest.mark.parametrize(
    "percent,labels,exit_code",
    [
        ("50", "[]", 1),
        ("", json.dumps(["ci-backend-depot"]), 1),
        ("5", "[]", 0),
        ("0", "[]", 0),
        ("", "[]", 0),
        ("50", json.dumps(["ci-backend-github"]), 0),
    ],
)
def test_main_fails_on_an_unreadable_handoff_only_when_depot_would_run(
    percent: str, labels: str, exit_code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(repo: str, sha: str, token: str) -> list[dict[str, Any]]:
        raise route.HandoffReadError("boom")

    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PERCENT", percent)
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", labels)
    monkeypatch.setenv("REPO", "PostHog/posthog")
    monkeypatch.setenv("SHA", "abc")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(route, "fetch_handoff_checks", failing)
    monkeypatch.setattr(route.time, "sleep", lambda seconds: None)
    assert route.main() == exit_code
    if exit_code:
        assert not output.exists()
    else:
        assert output.read_text().startswith("engine=github\n")
