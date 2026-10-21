import json
import subprocess
from typing import Any

import pytest

import ci_backend_depot_failures as depot_failures


def stub_diagnose(monkeypatch: pytest.MonkeyPatch, outcome: str | BaseException) -> None:
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(outcome, BaseException):
            raise outcome
        return subprocess.CompletedProcess(args, 0, stdout=outcome)

    monkeypatch.setattr(depot_failures.subprocess, "run", run)


def test_log_lines_stay_inside_one_escaped_annotation(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["##[error]FAILED test_widget - 100% broken", "::add-mask::ghp_example", "tail\r\n::set-output name=x::y"]
    attempt = {
        "job_display_name": "Repo checks",
        "error_message": "Step 3 (Validate widgets): exit 1",
        "relevant_lines": [{"content": line} for line in lines],
    }
    stub_diagnose(monkeypatch, json.dumps({"representative_attempts": [attempt]}))

    assert depot_failures.explain("org", "workflow") == [
        "::error title=Failed on Depot::Repo checks: Step 3 (Validate widgets): exit 1"
        "%0AFAILED test_widget - 100%25 broken"
        "%0A::add-mask::ghp_example"
        "%0Atail%0D%0A::set-output name=x::y"
    ]


@pytest.mark.parametrize(
    "outcome, error",
    [
        (FileNotFoundError("depot"), "FileNotFoundError"),
        (subprocess.CalledProcessError(1, "depot"), "CalledProcessError"),
        ("not json", "JSONDecodeError"),
    ],
)
def test_unreadable_diagnosis_leaves_one_warning(
    monkeypatch: pytest.MonkeyPatch, outcome: str | BaseException, error: str
) -> None:
    stub_diagnose(monkeypatch, outcome)

    assert depot_failures.explain("org", "workflow") == [f"::warning::Cannot read the Depot failure details: {error}"]
