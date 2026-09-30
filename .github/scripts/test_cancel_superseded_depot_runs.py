import importlib.util
from datetime import datetime
from pathlib import Path

from parameterized import parameterized

SCRIPT_PATH = Path(__file__).with_name("cancel_superseded_depot_runs.py")
SPEC = importlib.util.spec_from_file_location("cancel_superseded_depot_runs", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
cancel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cancel)


def run(run_id: str, second: int, head_sha: str = "head") -> "cancel.Run":
    return cancel.Run(
        run_id=run_id, created_at=datetime.fromisoformat(f"2026-09-30T12:00:{second:02d}Z"), head_sha=head_sha
    )


def workflow(run_id: str, status: str = "running", path: str = "ci-backend.yml") -> "cancel.Workflow":
    return cancel.Workflow(workflow_id=f"w{run_id}", run_id=run_id, path=path, status=status)


class FakeDepot:
    def __init__(self, polls: list[tuple[list["cancel.Workflow"], list["cancel.Run"]]]) -> None:
        self._polls = polls
        self._poll = -1
        self.cancelled: list[str] = []

    def workflows(self) -> list["cancel.Workflow"]:
        self._poll = min(self._poll + 1, len(self._polls) - 1)
        return self._polls[self._poll][0]

    def active_runs(self) -> list["cancel.Run"]:
        return self._polls[self._poll][1]

    def cancel(self, workflow: "cancel.Workflow") -> None:
        self.cancelled.append(workflow.run_id)


class TestCancelSuperseded:
    @parameterized.expand(
        [
            ("older_run", [run("old", 0), run("me", 5)], [workflow("old")], ["old"]),
            ("newer_run", [run("me", 0), run("new", 5)], [workflow("new")], []),
            ("same_commit_tie_keeps_higher_id", [run("a", 5), run("me", 5)], [workflow("a")], ["a"]),
            ("same_commit_tie_lower_id_keeps_other", [run("me", 5), run("z", 5)], [workflow("z")], []),
            ("two_commit_tie_keeps_both", [run("a", 5, "other"), run("me", 5)], [workflow("a")], []),
            ("ended_workflow", [run("old", 0), run("me", 5)], [workflow("old", status="cancelled")], []),
            ("other_workflow_file", [run("old", 0), run("me", 5)], [workflow("old", path="other.yml")], []),
        ]
    )
    def test_cancels_only_runs_this_event_superseded(
        self, _name: str, runs: list["cancel.Run"], others: list["cancel.Workflow"], expected: list[str]
    ) -> None:
        depot = FakeDepot([([workflow("me"), *others], runs)])

        assert cancel.cancel_superseded(depot, "wme", sleep=lambda _: None)
        assert depot.cancelled == expected

    def test_waits_for_an_older_run_to_get_its_workflow(self) -> None:
        runs = [run("old", 0), run("me", 5)]
        depot = FakeDepot([([workflow("me")], runs), ([workflow("me"), workflow("old")], runs)])

        assert cancel.cancel_superseded(depot, "wme", sleep=lambda _: None)
        assert depot.cancelled == ["old"]
