"""Hold the directories that contain test files with no team owner to a list that only shrinks.

owners.yaml decides which team a test's failures reach: Trunk attributes flaky tests through
the CODEOWNERS projection that `.github/scripts/trunk-codeowners.sh` builds from it. A test
that resolves to no team reaches nobody when it breaks.

The list holds directories, not files, because a new file inherits the owner of its directory.
A new test in a listed directory passes until the directory gets an owner. A new directory of
unowned tests fails. A listed directory whose tests all have an owner also fails, so the change
that assigns the owner removes the directory from the list.

Regenerate the baseline (it only drops directories, never adds them):

    PYTHONPATH=. python posthog/test/repo_invariants/test_unowned_test_directories.py
"""

from datetime import date
from pathlib import Path, PurePosixPath

from owners_yaml import OwnersResolver, first_team_owner, runner_for_path

from posthog.test.repo_invariants.ratchet import enforce_baseline

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).with_name("unowned_test_directories_baseline.txt")
BLOCKING_FROM = date.fromisoformat("2026-11-02")
REGENERATE = "PYTHONPATH=. python posthog/test/repo_invariants/test_unowned_test_directories.py"


def unowned_test_directories() -> set[str]:
    resolver = OwnersResolver(REPO_ROOT)
    directories: set[str] = set()
    for path in resolver.tracked_files():
        if runner_for_path(path) is None:
            continue
        resolution = resolver.resolve(path)
        if resolution.unowned_by_design or first_team_owner(resolution.owners):
            continue
        directories.add(str(PurePosixPath(path).parent))
    return directories


def read_baseline() -> set[str]:
    return {line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line}


def write_baseline(directories: set[str]) -> None:
    BASELINE.write_text("".join(f"{directory}\n" for directory in sorted(directories)), encoding="utf-8")


def test_no_new_directories_of_unowned_tests() -> None:
    current = unowned_test_directories()
    baseline = read_baseline()
    added = sorted(current - baseline)
    removed = sorted(baseline - current)
    lines: list[str] = []
    if added:
        lines += [
            "These directories hold test files that no team owns, so their failures reach nobody.",
            "Name the owning team in the nearest owners.yaml. `hogli owners:who <path>` shows which file applies.",
            *(f"  {directory}" for directory in added),
        ]
    if removed:
        lines += [
            f"These directories no longer hold unowned tests. Remove them from {BASELINE.name}:",
            f"  {REGENERATE}",
            *(f"  {directory}" for directory in removed),
        ]
    enforce_baseline(added=added, removed=removed, blocking_from=BLOCKING_FROM, message="\n".join(lines))


if __name__ == "__main__":
    write_baseline(unowned_test_directories() & read_baseline())
