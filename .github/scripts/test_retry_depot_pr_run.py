import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("retry_depot_pr_run.py")
SPEC = importlib.util.spec_from_file_location("retry_depot_pr_run", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


def run(run_id: str, second: int) -> dict[str, str]:
    return {"run_id": run_id, "created_at": f"2026-10-16T12:00:{second:02d}Z"}


def workflow(workflow_id: str, *job_statuses: str) -> dict[str, Any]:
    return {"workflow_id": workflow_id, "jobs": [{"status": status} for status in job_statuses]}


@pytest.mark.parametrize(
    "runs,expected",
    [
        pytest.param([run("b", 9), run("a", 5)], "b", id="newest_by_time"),
        pytest.param([run("z", 5), run("a", 5)], "z", id="same_second_tie_keeps_list_order"),
        pytest.param([], None, id="no_runs"),
    ],
)
def test_newest_run_id(runs: list[dict[str, str]], expected: str | None) -> None:
    assert script.newest_run_id(runs) == expected


@pytest.mark.parametrize(
    "workflows,expected",
    [
        pytest.param([workflow("w", "finished", "running", "failed")], ["w"], id="failed_job_mid_run"),
        pytest.param([workflow("w", "finished", "cancelled")], ["w"], id="cancelled_job"),
        pytest.param([workflow("w", "finished", "skipped", "running")], [], id="nothing_failed"),
        pytest.param([workflow("a", "failed"), workflow("b", "finished")], ["a"], id="only_failed_workflow"),
    ],
)
def test_retryable_workflow_ids(workflows: list[dict[str, Any]], expected: list[str]) -> None:
    assert script.retryable_workflow_ids({"workflows": workflows}) == expected
