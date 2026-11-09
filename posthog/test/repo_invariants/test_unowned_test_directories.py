from hogli_commands.ownership_lint import baseline_drift, drift_problems, prune_baseline


def test_unowned_test_directories_match_the_baseline() -> None:
    drift = baseline_drift()
    assert not (drift.added or drift.removed), "\n".join(
        [
            "A failing test with no team owner reaches nobody. `hogli owners:who <path>` shows which owners.yaml applies.",
            *drift_problems(drift),
        ]
    )


if __name__ == "__main__":
    prune_baseline()
