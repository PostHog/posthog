from datetime import date

from hogli_commands.ownership_lint import baseline_drift, drift_problems, prune_baseline

from posthog.test.repo_invariants.ratchet import enforce_baseline

BLOCKING_FROM = date(2026, 11, 13)


def test_unowned_test_directories_match_the_baseline() -> None:
    drift = baseline_drift()
    message = "\n".join(
        [
            "A failing test with no team owner reaches nobody. `hogli owners:who <path>` shows which owners.yaml applies.",
            *drift_problems(drift),
        ]
    )
    enforce_baseline(added=drift.added, removed=drift.removed, blocking_from=BLOCKING_FROM, message=message)


if __name__ == "__main__":
    prune_baseline()
