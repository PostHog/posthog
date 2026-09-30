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


def at(second: int) -> datetime:
    return datetime.fromisoformat(f"2026-09-30T12:00:{second:02d}Z")


def run(run_id: str, second: int) -> "script.Run":
    return script.Run(run_id=run_id, created_at=at(second))


def workflow(run_id: str, path: str = "ci-backend.yml") -> "script.Workflow":
    return script.Workflow(workflow_id=f"w{run_id}", run_id=run_id, path=path)


@pytest.mark.parametrize(
    "runs,expected",
    [
        pytest.param([run("old", 0), run("mine", 6)], ["old"], id="run_created_before_the_event"),
        pytest.param([run("mine", 6), run("new", 9)], [], id="own_and_later_runs_kept"),
        pytest.param([run("same_second", 5)], [], id="run_created_in_the_event_second_kept"),
    ],
)
def test_superseded_cancels_only_runs_created_before_the_kept_event(
    runs: list["script.Run"], expected: list[str]
) -> None:
    workflows = [workflow(each.run_id) for each in runs]

    assert [target.run_id for target in script.superseded(at(5), workflows, runs)] == expected


def test_superseded_ignores_other_workflow_files() -> None:
    assert script.superseded(at(5), [workflow("old", path="other.yml")], [run("old", 0)]) == []
