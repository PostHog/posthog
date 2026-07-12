from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from products.cohorts.backend.management.commands.compare_cohort_membership import _collect_warnings
from products.cohorts.backend.parity.kafka_io import DrainStats

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=1)


def _complete_drain(**overrides) -> DrainStats:
    stats = DrainStats(partitions=4, partitions_read=4, consumed=10, reached_end=True)
    for key, value in overrides.items():
        setattr(stats, key, value)
    return stats


class TestCollectWarnings(SimpleTestCase):
    def test_clean_complete_drain_yields_no_warnings(self) -> None:
        warnings, infos = _collect_warnings(_complete_drain(earliest_retained=SINCE), set(), SINCE, NOW)
        self.assertEqual(warnings, [])
        self.assertEqual(len(infos), 1)
        self.assertIn("earliest retained", infos[0])

    def test_clipped_partitions_warn_instead_of_info(self) -> None:
        stats = _complete_drain(earliest_retained=NOW - timedelta(hours=1), maybe_clipped_partitions=[3, 1])
        warnings, infos = _collect_warnings(stats, set(), SINCE, NOW)
        self.assertEqual(infos, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("[1, 3]", warnings[0])
        self.assertIn("incomplete", warnings[0])

    def test_partial_drain_warns(self) -> None:
        warnings, _infos = _collect_warnings(_complete_drain(reached_end=False), set(), SINCE, NOW)
        self.assertTrue(any("fold is partial" in w for w in warnings))

    def test_retention_deadline_warns_within_a_day(self) -> None:
        old_since = NOW - timedelta(days=6, hours=1)
        warnings, _infos = _collect_warnings(_complete_drain(), set(), old_since, NOW)
        self.assertTrue(any("completeness expires" in w for w in warnings))

        fresh_since = NOW - timedelta(days=1)
        warnings, _infos = _collect_warnings(_complete_drain(), set(), fresh_since, NOW)
        self.assertFalse(any("completeness expires" in w for w in warnings))

    def test_unknown_cohorts_warn(self) -> None:
        warnings, _infos = _collect_warnings(_complete_drain(), {42, 7}, SINCE, NOW)
        self.assertTrue(any("absent from the realtime universe" in w and "[7, 42]" in w for w in warnings))
