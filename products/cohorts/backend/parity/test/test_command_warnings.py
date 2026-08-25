from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.management.commands.compare_cohort_membership import (
    _ALL_MODE_FLAGS,
    _MODE_FLAGS,
    DEFAULT_THRESHOLD_PCT,
    Command,
    PopulationCohortState,
    RecomputeCohortState,
    _collect_population_warnings,
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


_UNSET_FLAGS: dict[str, Any] = {
    "threshold": None,
    "warmup_sample": None,
    "no_classify": False,
    "at": None,
    "run_id": None,
    "grace_minutes": None,
    "max_window_days": None,
    "max_oracle_members": None,
    "with_ids": False,
}


class TestRejectFlags(SimpleTestCase):
    @parameterized.expand(
        [
            # Every mode-specific flag defaults to None (False for a store_true) precisely so a value
            # that happens to equal the documented default is still rejected rather than silently
            # ignored by another oracle.
            ("recompute_rejects_explicit_documented_default", "recompute", {"threshold": DEFAULT_THRESHOLD_PCT}, True),
            ("recompute_rejects_explicit_zero", "recompute", {"warmup_sample": 0}, True),
            ("recompute_rejects_store_true", "recompute", {"no_classify": True}, True),
            ("recompute_rejects_population_flag", "recompute", {"with_ids": True}, True),
            ("recompute_accepts_own_flag", "recompute", {"grace_minutes": 0}, False),
            ("population_rejects_recompute_flag", "population", {"at": "2026-07-30T00:00:00Z"}, True),
            ("population_rejects_old_pipeline_flag", "population", {"threshold": 1.0}, True),
            ("population_accepts_own_flag", "population", {"with_ids": True}, False),
            # max_oracle_members is owned by two modes; collapsing the registry back to single-owner
            # would make population reject the cap it needs against oversized cohortpeople reads.
            ("population_accepts_shared_max_oracle_members", "population", {"max_oracle_members": 5}, False),
            ("old_pipeline_rejects_population_flag", "old-pipeline", {"with_ids": True}, True),
            ("old_pipeline_accepts_own_flag", "old-pipeline", {"no_classify": True}, False),
            ("nothing_set", "population", {}, False),
        ]
    )
    def test_each_mode_rejects_only_the_flags_it_does_not_own(
        self, _name: str, mode: str, overrides: dict, expect_error: bool
    ) -> None:
        options = {**_UNSET_FLAGS, **overrides}
        if not expect_error:
            _reject_flags(options, mode)
            return
        with self.assertRaises(CommandError):
            _reject_flags(options, mode)

    def test_every_mode_only_flag_matches_the_registry(self) -> None:
        # A flag in the registry but missing from the parser fails loudly (KeyError on options), but
        # a parser flag missing from the registry is silently accepted by every other oracle. The
        # "<modes> only:" help prefix is the one place each flag names its owners, so hold it and
        # the registry in sync, in both directions.
        parser = Command().create_parser("manage.py", "compare_cohort_membership")
        prefixed: list[str] = []
        for action in parser._actions:
            owner_part, sep, _rest = (action.help or "").partition(" only:")
            if not sep:
                continue
            prefixed.append(action.dest)
            owners = owner_part.split("/")
            for mode, flags in _MODE_FLAGS.items():
                self.assertEqual(
                    action.dest in flags,
                    mode in owners,
                    f"--{action.dest.replace('_', '-')}: help names {owners} but the registry owners "
                    f"are {[m for m, f in _MODE_FLAGS.items() if action.dest in f]}",
                )
        self.assertEqual(sorted(prefixed), list(_ALL_MODE_FLAGS))


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


class TestCollectPopulationWarnings(SimpleTestCase):
    def test_clean_state_yields_no_warnings(self) -> None:
        state = PopulationCohortState(
            cohort_id=1, last_calculation=NOW, is_calculating=False, has_complete_reconcile=True
        )
        self.assertEqual(_collect_population_warnings(now=NOW, states=[state]), [])

    def test_each_way_a_population_row_can_be_misread_is_called_out(self) -> None:
        # Without these the report reads as a like-for-like diff: only_legacy looks like a miss count
        # rather than an upper bound, a fold that cannot reach back looks like a real under-count, and
        # a population being rewritten under the read looks settled.
        state = PopulationCohortState(
            cohort_id=7,
            last_calculation=NOW - timedelta(days=8),
            is_calculating=True,
            has_complete_reconcile=False,
        )
        warnings = _collect_population_warnings(now=NOW, states=[state])
        self.assertTrue(any("no complete 64/64 reconcile" in w and "upper bound" in w for w in warnings))
        self.assertTrue(any("retention floor" in w for w in warnings))
        self.assertTrue(any("is_calculating" in w for w in warnings))
