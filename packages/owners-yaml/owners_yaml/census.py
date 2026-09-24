"""Per-team census of the repo's test files, resolved through the distributed owners.yaml
map. A static read of the tree, so it carries the denominator the signal-only CI spans cannot."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .resolver import OwnersResolver

UNOWNED_TEAM = "unowned"

_PYTEST_FILE = re.compile(r"(^|/)test_[^/]*\.py$|_test\.py$")
_JEST_FILE = re.compile(r"\.(test|spec)\.[jt]sx?$")


def first_team_owner(owners: list[str] | None) -> str:
    """First owner that is a team slug; an ``@handle`` is a person, not a team."""
    return next((owner for owner in owners or [] if not owner.startswith("@")), "")


def runner_for_path(path: str) -> str | None:
    if _PYTEST_FILE.search(path):
        return "pytest"
    if _JEST_FILE.search(path):
        return "jest"
    return None


@dataclass(frozen=True, kw_only=True, slots=True)
class TeamTestCensus:
    owner_team: str
    pytest_file_count: int
    jest_file_count: int

    @property
    def test_file_count(self) -> int:
        return self.pytest_file_count + self.jest_file_count

    def as_payload(self) -> dict[str, int | str]:
        """The wire shape shared by ``owners:census --json`` and the census events."""
        return {
            "owner_team": self.owner_team,
            "pytest_file_count": self.pytest_file_count,
            "jest_file_count": self.jest_file_count,
            "test_file_count": self.test_file_count,
        }


def census(paths: Iterable[str], repo_root: Path) -> list[TeamTestCensus]:
    """Count test files per owning team over repo-relative ``paths``, most tests first.
    Uncovered files and files owned only by ``@handles`` count under ``unowned``."""
    resolver = OwnersResolver(repo_root)
    counts: dict[str, dict[str, int]] = {}
    for path in paths:
        runner = runner_for_path(path)
        if runner is None:
            continue
        team = first_team_owner(resolver.resolve(path).owners) or UNOWNED_TEAM
        counts.setdefault(team, {"pytest": 0, "jest": 0})[runner] += 1
    return sorted(
        (
            TeamTestCensus(
                owner_team=team,
                pytest_file_count=by_runner["pytest"],
                jest_file_count=by_runner["jest"],
            )
            for team, by_runner in counts.items()
        ),
        key=lambda c: (-c.test_file_count, c.owner_team),
    )
