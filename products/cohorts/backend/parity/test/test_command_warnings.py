from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.management.commands.compare_cohort_membership import (
    DEFAULT_THRESHOLD_PCT,
    RecomputeCohortState,
    _collect_recompute_warnings,
    _collect_warnings,
    _reject_flags,
)
from products.cohorts.backend.parity.kafka_io import DrainStats
from products.cohorts.backend.parity.recompute import RunContext

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


class TestRejectFlags(SimpleTestCase):
    @parameterized.expand(
        [
            # Every mode-specific flag defaults to None precisely so a value that happens to equal the
            # documented default is still rejected rather than silently ignored by the other oracle.
            ("explicit_documented_default", {"threshold": DEFAULT_THRESHOLD_PCT}, True),
            ("explicit_zero", {"warmup_sample": 0}, True),
            ("store_true_set", {"no_classify": True}, True),
            ("unset", {}, False),
        ]
    )
    def test_explicit_values_are_rejected_even_when_they_match_the_default(
        self, _name: str, overrides: dict, expect_error: bool
    ) -> None:
        options: dict[str, Any] = {"threshold": None, "warmup_sample": None, "no_classify": False, **overrides}
        flags = ("threshold", "warmup_sample", "no_classify")
        if not expect_error:
            _reject_flags(options, flags, "recompute")
            return
        with self.assertRaises(CommandError):
            _reject_flags(options, flags, "recompute")


def _ctx(**overrides: Any) -> RunContext:
    defaults: dict[str, Any] = {
        "run_id": "r",
        "status": "seeding",
        "boundary_at": NOW - timedelta(hours=6),
        "run_timezone": "US/Pacific",
        "boundary_day": date(2026, 7, 8),
        "confirmed_days": frozenset(),
        "non_confirmed_chunks": 0,
        "shape_hash_drift": False,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


class TestCollectRecomputeWarnings(SimpleTestCase):
    def test_clean_state_yields_no_warnings(self) -> None:
        state = RecomputeCohortState(cohort_id=1, ctx=_ctx(run_timezone="US/Pacific"), has_complete_reconcile=True)
        warnings = _collect_recompute_warnings(at=NOW, now=NOW, team_timezone="US/Pacific", states=[state])
        self.assertEqual(warnings, [])

    def test_stale_at_warns(self) -> None:
        warnings = _collect_recompute_warnings(
            at=NOW - timedelta(minutes=30), now=NOW, team_timezone="US/Pacific", states=[]
        )
        self.assertTrue(any("before now" in w for w in warnings))

    def test_missing_run_context_warns(self) -> None:
        state = RecomputeCohortState(cohort_id=5, ctx=None, has_complete_reconcile=True)
        warnings = _collect_recompute_warnings(at=NOW, now=NOW, team_timezone="US/Pacific", states=[state])
        self.assertTrue(any("no backfill run" in w and "cohort 5" in w for w in warnings))

    def test_per_cohort_context_warnings(self) -> None:
        state = RecomputeCohortState(
            cohort_id=9,
            ctx=_ctx(run_timezone="UTC", shape_hash_drift=True, non_confirmed_chunks=3),
            has_complete_reconcile=False,
        )
        warnings = _collect_recompute_warnings(at=NOW, now=NOW, team_timezone="US/Pacific", states=[state])
        self.assertTrue(any("run tz UTC != team tz US/Pacific" in w and "SKIPPED" in w for w in warnings))
        self.assertTrue(any("shape-hash" in w for w in warnings))
        self.assertTrue(any("3 seed chunk(s) not confirmed" in w for w in warnings))
        self.assertTrue(any("no complete 64/64 reconcile" in w for w in warnings))
