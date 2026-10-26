"""Per-team census of the repo's test files, resolved through the distributed owners.yaml
map. A static read of the tree, so it carries the denominator the signal-only CI spans cannot."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .resolver import OwnersResolver, Resolution

UNOWNED_TEAM = "unowned"

_PYTEST_FILE = re.compile(r"(^|/)test_[^/]*\.py$|_test\.py$")
_JEST_FILE = re.compile(r"\.(test|spec)\.[jt]sx?$")
# The same two patterns as fnmatch globs, where `*` spans `/`. Keep them in step with the regexes.
TEST_FILE_GLOBS = (
    "test_*.py",
    "*/test_*.py",
    "*_test.py",
    *(f"*.{kind}.{ext}" for kind in ("test", "spec") for ext in ("js", "jsx", "ts", "tsx")),
)


def first_team_owner(owners: list[str] | None) -> str:
    """First owner that is a team slug; an ``@handle`` is a person, not a team."""
    return next((owner for owner in owners or [] if not owner.startswith("@")), "")


def owning_team(resolution: Resolution) -> str | None:
    """The team that a test file's failures reach, or ``unowned`` when no team owns it.
    ``None`` for an ``owners: null`` exemption, which a coverage report must not count (SPEC section 3.1)."""
    if resolution.unowned_by_design:
        return None
    return first_team_owner(resolution.owners) or UNOWNED_TEAM


def runner_for_path(path: str) -> str | None:
    if _PYTEST_FILE.search(path):
        return "pytest"
    if _JEST_FILE.search(path):
        return "jest"
    return None


def unowned_test_directories(resolver: OwnersResolver) -> set[str]:
    """Directories that hold a tracked test file whose failures reach no team. A new file inherits
    the owner of its directory, so a baseline of directories stays steady while files come and go."""
    return {
        str(PurePosixPath(path).parent)
        for path in resolver.tracked_files()
        if runner_for_path(path) and owning_team(resolver.resolve(path)) == UNOWNED_TEAM
    }


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
    Uncovered files and files owned only by ``@handles`` count under ``unowned``, and files that
    ``owners: null`` exempts are left out."""
    resolver = OwnersResolver(repo_root)
    counts: dict[str, dict[str, int]] = {}
    for path in paths:
        runner = runner_for_path(path)
        if runner is None:
            continue
        team = owning_team(resolver.resolve(path))
        if team is None:
            continue
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
