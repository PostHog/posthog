from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.fold import fold_membership_changes, members, parse_last_updated

SINCE = datetime(2026, 7, 7, 19, 0, tzinfo=UTC)


def _msg(status: str, ts: str, *, cohort_id: int | None = 10, person_id: str = "P1", team_id: int = 2) -> dict:
    return {
        "team_id": team_id,
        "cohort_id": cohort_id,
        "person_id": person_id,
        "last_updated": ts,
        "status": status,
    }


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
