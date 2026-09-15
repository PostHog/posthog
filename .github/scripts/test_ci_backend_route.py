import io
import json
import urllib.error
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("ci_backend_route.py")
SPEC = importlib.util.spec_from_file_location("ci_backend_route", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
route = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route)


def pr(platform="depot", percent=25, number=124, labels=(), fork=False, draft=False):
    return route.decide(platform, "pull_request", percent, number, list(labels), fork, draft)


@pytest.mark.parametrize(
    "number,percent,expected",
    [(124, 25, "depot"), (125, 25, "github"), (100, 0, "github"), (199, 100, "depot"), (0, 1, "depot")],
)
def test_bucket_is_pr_number_mod_100(number, percent, expected):
    assert pr(number=number, percent=percent).route == expected


def test_same_answer_on_both_engines():
    assert pr(platform="github").route == pr(platform="depot").route == "depot"


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
def test_overrides(labels, fork, draft, expected):
    assert pr(labels=labels, fork=fork, draft=draft).route == expected


@pytest.mark.parametrize(
    "platform,event,percent,expected",
    [
        ("depot", "workflow_dispatch", 0, "depot"),
        ("github", "workflow_dispatch", 100, "github"),
        ("depot", "push", 0, "github"),
        ("depot", "push", 5, "depot"),
        ("github", "push", 100, "github"),
        ("github", "schedule", 100, "github"),
    ],
)
def test_non_pull_request_events(platform, event, percent, expected):
    assert route.decide(platform, event, percent, None, [], False, False).route == expected


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 0), ("", 0), ("abc", 0), ("-5", 0), ("42", 42), ("250", 100), (" 7 ", 7), ("\u00b2", 0), ("9" * 5000, 0)],
)
def test_parse_percent_fails_closed(raw, expected):
    assert route.parse_percent(raw) == expected


def test_fetch_percent_reads_value():
    class Response(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    value = route.fetch_percent(
        "PostHog/posthog", "token", opener=lambda request: Response(json.dumps({"value": "30"}))
    )
    assert value == "30"


def test_fetch_percent_returns_none_on_http_error():
    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    assert route.fetch_percent("PostHog/posthog", "token", opener=opener) is None


def test_main_treats_null_labels_as_none(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("EVENT", "push")
    monkeypatch.setenv("PERCENT", "50")
    monkeypatch.setenv("LABELS", "null")
    assert route.main() == 0
    assert output.read_text().startswith("route=github\n")


def test_main_writes_outputs(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("PERCENT", "50")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("LABELS", json.dumps(["other"]))
    assert route.main() == 0
    assert output.read_text() == "route=depot\nreason=bucket 7 < 50%\n"
