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
    assert route.decide(event, 100, None, ["ci-backend-depot"], False, False).engine == "github"


def test_missing_pr_number_stays_on_github() -> None:
    assert pr(number=None, percent=100).engine == "github"


@pytest.mark.parametrize(
    "prior,labels,percent,expected",
    [
        ("depot", ["ci-backend-github"], 0, "depot"),
        ("github", ["ci-backend-depot"], 100, "github"),
        ("", ["ci-backend-depot"], 0, "depot"),
        (None, [], 100, "depot"),
    ],
)
def test_earlier_run_of_the_commit_wins(prior: str | None, labels: list[str], percent: int, expected: str) -> None:
    assert route.decide("pull_request", percent, 124, labels, False, False, prior).engine == expected


def test_earlier_run_never_routes_a_non_pull_request_event() -> None:
    assert route.decide("push", 100, None, [], False, False, "depot").engine == "github"


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 0), ("", 0), ("abc", 0), ("-5", 0), ("42", 42), ("250", 100), (" 7 ", 7), ("²", 0), ("9" * 5000, 0)],
)
def test_parse_percent_fails_closed(raw: str | None, expected: int) -> None:
    assert route.parse_percent(raw) == expected


def test_main_treats_null_labels_as_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("EVENT", "push")
    monkeypatch.setenv("PERCENT", "50")
    monkeypatch.setenv("LABELS", "null")
    assert route.main() == 0
    assert output.read_text().startswith("engine=github\n")


def test_main_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PERCENT", "50")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", json.dumps(["other"]))
    assert route.main() == 0
    assert output.read_text() == "engine=depot\nreason=bucket 7 < 50%\n"
