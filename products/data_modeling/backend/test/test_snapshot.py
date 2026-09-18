from datetime import UTC, datetime

import pytest

from products.data_modeling.backend.logic.snapshot import SnapshotConfig, SnapshotValidationError, apply_snapshot


def at(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


def test_initial_snapshot_and_unchanged_observation_preserve_versions() -> None:
    config = SnapshotConfig(unique_key=("id",))
    first = apply_snapshot([], [{"id": 1, "name": "A"}], config=config, observed_at=at(1), generation="g", run_id="r1")
    second = apply_snapshot(
        first.history, [{"id": 1, "name": "A"}], config=config, observed_at=at(2), generation="g", run_id="r2"
    )

    assert first.stats.inserted == 1
    assert second.stats.unchanged == 1
    assert len(second.history) == 1
    assert second.history[0]["valid_to"] is None


def test_snapshot_closes_changed_and_missing_rows_and_reopens_rows() -> None:
    config = SnapshotConfig(unique_key=("account", "region"))
    first = apply_snapshot(
        [],
        [{"account": "a", "region": "us", "value": 1}, {"account": "b", "region": "eu", "value": 2}],
        config=config,
        observed_at=at(1),
        generation="g",
        run_id="r1",
    )
    second = apply_snapshot(
        first.history,
        [{"account": "a", "region": "us", "value": 3}],
        config=config,
        observed_at=at(2),
        generation="g",
        run_id="r2",
    )
    third = apply_snapshot(
        second.history,
        [{"account": "a", "region": "us", "value": 3}, {"account": "b", "region": "eu", "value": 4}],
        config=config,
        observed_at=at(3),
        generation="g",
        run_id="r3",
    )

    assert second.stats.changed == 1
    assert second.stats.removed == 1
    assert third.stats.inserted == 1
    assert len(third.history) == 4
    assert sum(row["valid_to"] is None for row in third.history) == 2


@pytest.mark.parametrize(
    "rows",
    [
        [{"id": None, "value": 1}],
        [{"id": 1, "value": 1}, {"id": 1, "value": 2}],
        [{"id": 1, "valid_from": "reserved"}],
    ],
)
def test_snapshot_rejects_invalid_observations(rows: list[dict[str, object]]) -> None:
    with pytest.raises(SnapshotValidationError):
        apply_snapshot(
            [], rows, config=SnapshotConfig(unique_key=("id",)), observed_at=at(1), generation="g", run_id="r"
        )


def test_snapshot_is_null_safe_and_column_order_independent() -> None:
    config = SnapshotConfig(unique_key=("id",))
    first = apply_snapshot(
        [],
        [{"id": 1, "nested": {"b": None, "a": 1}, "value": None}],
        config=config,
        observed_at=at(1),
        generation="g",
        run_id="r1",
    )
    second = apply_snapshot(
        first.history,
        [{"value": None, "nested": {"a": 1, "b": None}, "id": 1}],
        config=config,
        observed_at=at(2),
        generation="g",
        run_id="r2",
    )
    assert second.stats.unchanged == 1


def test_failed_observation_does_not_change_the_parent_history() -> None:
    config = SnapshotConfig(unique_key=("id",))
    first = apply_snapshot([], [{"id": 1, "value": 1}], config=config, observed_at=at(1), generation="g", run_id="r1")
    original = [dict(row) for row in first.history]
    with pytest.raises(SnapshotValidationError):
        apply_snapshot(
            first.history,
            [{"id": 1, "value": 2}, {"id": 1, "value": 3}],
            config=config,
            observed_at=at(2),
            generation="g",
            run_id="r2",
        )
    assert first.history == original


def test_reapplying_a_sealed_observation_has_the_same_version_id() -> None:
    config = SnapshotConfig(unique_key=("id",))
    first = apply_snapshot([], [{"id": 1, "value": 1}], config=config, observed_at=at(1), generation="g", run_id="r1")
    retry = apply_snapshot([], [{"id": 1, "value": 1}], config=config, observed_at=at(1), generation="g", run_id="r1")
    assert retry.history[0]["_ph_snapshot_version_id"] == first.history[0]["_ph_snapshot_version_id"]
