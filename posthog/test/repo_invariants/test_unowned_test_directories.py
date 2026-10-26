from datetime import date

from hogli_commands.ownership_lint import BASELINE, PRUNE, baseline_drift, prune_baseline

from posthog.test.repo_invariants.ratchet import enforce_baseline

BLOCKING_FROM = date.fromisoformat("2026-11-02")


def test_no_new_directories_of_unowned_tests() -> None:
    drift = baseline_drift()
    lines: list[str] = []
    if drift.added:
        lines += [
            "These directories hold test files that no team owns, so their failures reach nobody.",
            "Name the owning team in the nearest owners.yaml. `hogli owners:who <path>` shows which file applies.",
            *(f"  {directory}" for directory in drift.added),
        ]
    if drift.removed:
        lines += [
            f"These directories no longer hold unowned tests. Remove them from {BASELINE}:",
            f"  {PRUNE}",
            *(f"  {directory}" for directory in drift.removed),
        ]
    enforce_baseline(added=drift.added, removed=drift.removed, blocking_from=BLOCKING_FROM, message="\n".join(lines))


if __name__ == "__main__":
    prune_baseline()
