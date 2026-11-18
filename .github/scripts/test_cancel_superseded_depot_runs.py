import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("cancel_superseded_depot_runs.py")
SPEC = importlib.util.spec_from_file_location("cancel_superseded_depot_runs", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(script)


def run(run_id: str, second: int, head_sha: str = "head") -> "script.Run":
    return script.Run(
        run_id=run_id, created_at=datetime.fromisoformat(f"2026-09-30T12:00:{second:02d}Z"), head_sha=head_sha
    )


def workflow(run_id: str, path: str = "ci-backend.yml") -> "script.Workflow":
    return script.Workflow(workflow_id=f"w{run_id}", run_id=run_id, path=path)


@pytest.mark.parametrize(
    "runs,others,expected",
    [
        pytest.param([run("old", 0), run("me", 5)], ["old"], ["old"], id="older_run"),
        pytest.param([run("me", 0), run("new", 5)], ["new"], ["me"], id="newer_run_cancels_self"),
        pytest.param([run("old", 0), run("me", 5), run("new", 9)], ["old", "new"], ["me"], id="newer_run_leaves_older"),
        pytest.param([run("me", 0), run("new", 5)], [], ["me"], id="newer_run_already_ended"),
        pytest.param([run("a", 5), run("me", 5)], ["a"], ["a"], id="same_commit_tie_higher_id_wins"),
        pytest.param([run("me", 5), run("z", 5)], ["z"], ["me"], id="same_commit_tie_lower_id_loses"),
        pytest.param([run("a", 5, "other"), run("me", 5), run("z", 5, "other")], ["a", "z"], [], id="two_commit_tie"),
    ],
)
def test_superseded(runs: list["script.Run"], others: list[str], expected: list[str]) -> None:
    workflows = [workflow("me"), *(workflow(run_id) for run_id in others)]

    assert [target.run_id for target in script.superseded("wme", workflows, runs)] == expected


def test_superseded_ignores_other_workflow_files() -> None:
    workflows = [workflow("me"), workflow("old", path="other.yml")]

    assert script.superseded("wme", workflows, [run("old", 0), run("me", 5)]) == []
