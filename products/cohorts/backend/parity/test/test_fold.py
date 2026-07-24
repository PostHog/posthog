from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.fold import (
    LIVE_ORIGIN,
    fold_membership_changes,
    members,
    observed,
    parse_last_updated,
    reconcile_completeness,
)

SINCE = datetime(2026, 7, 7, 19, 0, tzinfo=UTC)
RUN_1 = "00000000-0000-0000-0000-000000000001"
RUN_2 = "00000000-0000-0000-0000-000000000002"


def _msg(status: str, ts: str, *, cohort_id: int | None = 10, person_id: str = "P1", team_id: int = 2) -> dict:
    return {
        "team_id": team_id,
        "cohort_id": cohort_id,
        "person_id": person_id,
        "last_updated": ts,
        "status": status,
    }


def _marker(
    partition: int,
    *,
    run_id: str = RUN_1,
    cohort_id: int = 10,
    team_id: int = 2,
    ts: str = "2026-07-07 19:05:00.000001",
) -> dict:
    return {
        "type": "reconcile_complete",
        "team_id": team_id,
        "cohort_id": cohort_id,
        "partition": partition,
        "run_id": run_id,
        "last_updated": ts,
    }


def _marker_without(field: str) -> dict:
    marker = _marker(1)
    del marker[field]
    return marker


class TestFold(SimpleTestCase):
    def test_last_message_wins_per_pair(self) -> None:
        state, stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 19:01:00.000001"),
                _msg("left", "2026-07-07 19:02:00.000001"),
                _msg("entered", "2026-07-07 19:03:00.000001"),
                _msg("entered", "2026-07-07 19:01:00.000001", person_id="P2"),
                _msg("left", "2026-07-07 19:02:00.000001", person_id="P2"),
            ],
            team_id=2,
            since=SINCE,
        )
        self.assertEqual(members(state[10]), {"p1"})
        self.assertEqual(stats.folded, 5)
        self.assertEqual(stats.cohorts_seen, {10})

    def test_observed_counts_both_entered_and_left(self) -> None:
        # The O-bounded diff hinges on `observed` returning every decided person, so a
        # person whose final state is `left` must still count as observed (unlike members).
        state, _stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 19:01:00.000001", person_id="P1"),
                _msg("left", "2026-07-07 19:02:00.000001", person_id="P1"),
                _msg("entered", "2026-07-07 19:01:00.000001", person_id="P2"),
            ],
            team_id=2,
            since=SINCE,
        )
        self.assertEqual(observed(state[10]), {"p1", "p2"})
        self.assertEqual(members(state[10]), {"p2"})

    def test_out_of_order_older_record_does_not_shadow_newer(self) -> None:
        state, _stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 19:03:00.000001"),
                _msg("left", "2026-07-07 19:02:00.000001"),
            ],
            team_id=2,
            since=SINCE,
        )
        self.assertEqual(members(state[10]), {"p1"})

    def test_since_cutoff_drops_pre_wipe_messages(self) -> None:
        state, stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 18:59:59.999999"),
                _msg("entered", "2026-07-07 19:00:00.000000", person_id="P2"),
            ],
            team_id=2,
            since=SINCE,
        )
        self.assertEqual(members(state[10]), {"p2"})
        self.assertEqual(stats.dropped_before_since, 1)

    def test_wrong_team_messages_are_dropped(self) -> None:
        state, stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 19:01:00.000001", team_id=99999),
                _msg("entered", "2026-07-07 19:01:00.000001", person_id="P2"),
            ],
            team_id=2,
            since=SINCE,
        )
        self.assertEqual(members(state[10]), {"p2"})
        self.assertEqual(stats.dropped_wrong_team, 1)

    def test_reconcile_marker_is_recorded_before_membership_validation(self) -> None:
        state, stats = fold_membership_changes(
            [
                _marker(7),
                _msg("entered", "2026-07-07 19:06:00.000001") | {"origin": "reconcile", "run_id": RUN_1},
            ],
            team_id=2,
            since=SINCE,
        )

        self.assertEqual(stats.reconcile_markers, {(RUN_1, 10): {7}})
        self.assertEqual(stats.dropped_malformed, 0)
        self.assertEqual(stats.cohorts_seen, {10})
        self.assertEqual(state[10]["p1"].origin, "reconcile")
        self.assertEqual(state[10]["p1"].run_id, RUN_1)

    def test_membership_provenance_follows_lww_and_counts_every_folded_origin(self) -> None:
        state, stats = fold_membership_changes(
            [
                _msg("entered", "2026-07-07 19:01:00.000001", person_id="P1"),
                _msg("entered", "2026-07-07 19:02:00.000001", person_id="P2") | {"origin": "seed", "run_id": RUN_1},
                _msg("left", "2026-07-07 19:03:00.000001", person_id="P1") | {"origin": "reconcile", "run_id": RUN_2},
            ],
            team_id=2,
            since=SINCE,
        )

        self.assertEqual(stats.folded_by_origin, {LIVE_ORIGIN: 1, "seed": 1, "reconcile": 1})
        self.assertEqual(
            (state[10]["p1"].status, state[10]["p1"].origin, state[10]["p1"].run_id), ("left", "reconcile", RUN_2)
        )
        self.assertEqual((state[10]["p2"].origin, state[10]["p2"].run_id), ("seed", RUN_1))

    def test_reconcile_completeness_is_per_run_and_counts_distinct_partitions(self) -> None:
        messages = [*(_marker(partition, run_id=RUN_2) for partition in range(64))]
        messages.extend(_marker(partition, run_id=RUN_1) for partition in range(41))
        messages.append(_marker(0, run_id=RUN_1))
        # A second cohort shares RUN_1 and covers exactly the partitions cohort 10 is missing
        # (41..64); its markers must stay under their own cohort so RUN_1 does not read as a
        # false 64/64 for cohort 10.
        messages.extend(_marker(partition, run_id=RUN_1, cohort_id=20) for partition in range(41, 64))

        _state, stats = fold_membership_changes(messages, team_id=2, since=SINCE)

        completeness = reconcile_completeness(stats, cohort_id=10)
        self.assertEqual(
            [(run.run_id, run.partitions_seen, run.complete) for run in completeness],
            [(RUN_1, 41, False), (RUN_2, 64, True)],
        )
        self.assertEqual(
            [(run.run_id, run.partitions_seen, run.complete) for run in reconcile_completeness(stats, cohort_id=20)],
            [(RUN_1, 23, False)],
        )
        # Counts every accepted marker message, including the RUN_1 partition-0 duplicate — 129,
        # not the 128 distinct partitions the completeness sets hold. Keeps the summary's
        # folded + drops + markers == total accounting exact.
        self.assertEqual(stats.reconcile_markers_recorded, 129)

    @parameterized.expand(
        [
            ("bad_run_id", _marker(1, run_id="not-a-uuid"), 2, 1, 0),
            ("missing_run_id", _marker_without("run_id"), 2, 1, 0),
            ("out_of_range_partition", _marker(64), 2, 1, 0),
            ("missing_partition", _marker_without("partition"), 2, 1, 0),
            ("missing_timestamp", _marker_without("last_updated"), 2, 1, 0),
            ("float_team_id", _marker(1) | {"team_id": 2.0}, 2, 1, 0),
            ("boolean_team_id", _marker(1, team_id=True), 1, 1, 0),
            ("before_since", _marker(1, ts="2026-07-07 18:59:59.999999"), 2, 0, 1),
        ]
    )
    def test_invalid_or_stale_markers_cannot_certify_reconcile(
        self,
        _name: str,
        marker: dict,
        team_id: int,
        expected_malformed: int,
        expected_before_since: int,
    ) -> None:
        _state, stats = fold_membership_changes([marker], team_id=team_id, since=SINCE)

        self.assertEqual(stats.reconcile_markers, {})
        self.assertEqual(stats.dropped_malformed, expected_malformed)
        self.assertEqual(stats.dropped_before_since, expected_before_since)

    @parameterized.expand(
        [
            ("rust_microseconds", "2026-07-07 19:01:00.123456"),
            ("python_microseconds", "2026-07-07 19:01:00.000042"),
            ("short_fraction", "2026-07-07 19:01:00.5"),
            ("no_fraction", "2026-07-07 19:01:00"),
        ]
    )
    def test_last_updated_renderings_parse_as_utc(self, _name: str, raw: str) -> None:
        parsed = parse_last_updated(raw)
        assert parsed is not None
        self.assertEqual(parsed.tzinfo, UTC)
        self.assertEqual(parsed.replace(microsecond=0), datetime(2026, 7, 7, 19, 1, 0, tzinfo=UTC))

    @parameterized.expand(
        [
            (
                "missing_person",
                {"team_id": 2, "cohort_id": 10, "status": "entered", "last_updated": "2026-07-07 19:01:00"},
            ),
            ("bad_status", _msg("member", "2026-07-07 19:01:00.000001")),
            ("bad_timestamp", _msg("entered", "07/07/2026")),
            ("non_int_cohort", _msg("entered", "2026-07-07 19:01:00.000001", cohort_id=None)),
        ]
    )
    def test_malformed_rows_are_skipped_and_counted(self, _name: str, message: dict) -> None:
        state, stats = fold_membership_changes([message], team_id=2, since=SINCE)
        self.assertEqual(state, {})
        self.assertEqual(stats.dropped_malformed, 1)
        self.assertEqual(stats.folded, 0)
