import math
from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.classifier import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    VERDICT_WARMUP,
    ClassifierConfig,
    classify_cohort,
    summarize,
)
from products.cohorts.backend.parity.eligibility import EXCLUDED_HAS_DROPPED_LEAF, SINGLE_LEAF, ScreenedCohort
from products.cohorts.backend.parity.fold import MembershipRecord

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=1)
LAST_CALC = NOW - timedelta(minutes=30)


def _screened(eligibility: str = SINGLE_LEAF, window: float | None = None) -> ScreenedCohort:
    return ScreenedCohort(cohort_id=1, eligibility=eligibility, max_window_days=window)


def _entered(persons: list[str], *, at: datetime) -> dict[str, MembershipRecord]:
    return {p: MembershipRecord(status="entered", last_updated=at) for p in persons}


def _state(records: dict[str, tuple[str, datetime]]) -> dict[str, MembershipRecord]:
    return {p: MembershipRecord(status=status, last_updated=at) for p, (status, at) in records.items()}


def _config(**overrides) -> ClassifierConfig:
    defaults: dict = {"since": SINCE, "now": NOW, "threshold_pct": 0.5, "warmup_sample": 5000}
    defaults.update(overrides)
    return ClassifierConfig(**defaults)


class TestClassifier(SimpleTestCase):
    def test_excluded_cohort_is_skipped_not_gated(self) -> None:
        row = classify_cohort(
            screened=_screened(EXCLUDED_HAS_DROPPED_LEAF),
            name="x",
            old_members={"a", "b"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(),
        )
        self.assertEqual(row.verdict, VERDICT_SKIP)
        self.assertFalse(row.gated)

    def test_fresh_rule_explains_new_entries_after_last_recompute(self) -> None:
        new_state = _entered(["a", "b"], at=NOW - timedelta(minutes=45)) | _entered(
            ["c"], at=NOW - timedelta(minutes=5)
        )
        row = classify_cohort(
            screened=_screened(),
            name="x",
            old_members={"a", "b"},
            new_state=new_state,
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=lambda persons, cutoff: set(persons)),
        )
        self.assertEqual(row.only_new, 1)
        self.assertEqual(row.fresh, 1)
        self.assertEqual(row.residual_new, 0)
        self.assertEqual(row.verdict, VERDICT_PASS)

    def test_never_recomputed_cohort_counts_all_only_new_as_fresh(self) -> None:
        row = classify_cohort(
            screened=_screened(),
            name="x",
            old_members=set(),
            new_state=_entered(["a", "b"], at=NOW - timedelta(hours=2)),
            last_realtime_calculation_at=None,
            config=_config(),
        )
        self.assertEqual(row.fresh, 2)
        self.assertEqual(row.verdict, VERDICT_PASS)

    def test_old_only_person_outside_O_is_excluded_and_dormant(self) -> None:
        # Old says entered, new never decided (person absent from O): the person leaves the
        # diff (only_old excludes them) and, being inactive, is dormant — no FAIL.
        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b", "c"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=lambda persons, cutoff: set()),
        )
        self.assertEqual((row.observed, row.only_old), (0, 0))
        self.assertEqual((row.unobserved, row.dormant, row.suspect_missing), (3, 3, 0))
        self.assertEqual(row.verdict, VERDICT_PASS)

    @parameterized.expand(
        [
            # flip newer than the old side's last recompute → R-STALE explains it → PASS
            ("flip_after_last_calc", NOW, 1, 0, VERDICT_PASS),
            # flip older → old has recomputed past it, so it is a genuine residual → FAIL
            ("flip_before_last_calc", LAST_CALC - timedelta(minutes=5), 0, 1, VERDICT_FAIL),
        ]
    )
    def test_r_stale_mirror(
        self, _name: str, flip_at: datetime, expected_stale: int, expected_residual_old: int, expected_verdict: str
    ) -> None:
        # Person p is in O (new flipped it to `left`) but old still says entered.
        row = classify_cohort(
            screened=_screened(),
            name="x",
            old_members={"p", "a"},
            new_state=_state({"p": ("left", flip_at), "a": ("entered", NOW)}),
            last_realtime_calculation_at=LAST_CALC,
            config=_config(),
        )
        self.assertEqual(row.only_old, 1)
        self.assertEqual(row.stale, expected_stale)
        self.assertEqual(row.residual_old, expected_residual_old)
        self.assertEqual(row.verdict, expected_verdict)

    def test_active_unobserved_on_sound_cohort_is_suspect_and_fails(self) -> None:
        # Dead-processor case: empty O, populated old, all recently active. The O-bounded
        # residual is 0, but the missed-emission probe gates FAIL on a sound cohort.
        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b", "c"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=lambda persons, cutoff: set(persons)),
        )
        self.assertEqual((row.observed, row.residual_old, row.residual_new), (0, 0, 0))
        self.assertEqual((row.suspect_missing, row.dormant), (3, 0))
        self.assertEqual(row.verdict, VERDICT_FAIL)

    def test_active_unobserved_on_long_window_cohort_is_warmup_not_gated(self) -> None:
        # Same active-unobserved population, but the behavioral window exceeds pipeline age:
        # the miss is unresolvable from a snapshot (pre-since qualifier), so WARMUP not FAIL.
        row = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a", "b", "c"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=lambda persons, cutoff: set(persons)),
        )
        self.assertEqual(row.suspect_missing, 3)
        self.assertEqual(row.verdict, VERDICT_WARMUP)
        self.assertFalse(row.gated)

    def test_warmup_sample_zero_skips_suspect_probe(self) -> None:
        probe_calls: list[list[str]] = []

        def probe(persons, cutoff):
            probe_calls.append(list(persons))
            return set(persons)

        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(warmup_sample=0, activity_probe=probe),
        )
        self.assertEqual(probe_calls, [])
        self.assertEqual((row.suspect_missing, row.dormant), (0, 2))
        self.assertEqual(row.verdict, VERDICT_PASS)
        self.assertTrue(any("suspect check skipped" in note for note in row.notes))

    @parameterized.expand(
        [
            ("no_window", None, SINCE),
            ("sub_day_window", 0.25, NOW - timedelta(days=0.25)),
            ("window_ge_pipeline_age", 30.0, SINCE),
            ("inf_window", math.inf, SINCE),  # would overflow timedelta without the guard
            ("zero_window", 0.0, NOW),  # minute/hour cohorts → cutoff collapses to now
        ]
    )
    def test_probe_cutoff_formula(self, _name: str, window: float | None, expected_cutoff: datetime) -> None:
        seen_cutoffs: list[datetime] = []

        def probe(persons, cutoff):
            seen_cutoffs.append(cutoff)
            return set()

        classify_cohort(
            screened=_screened(window=window),
            name="x",
            old_members={"a"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=probe),
        )
        self.assertEqual(seen_cutoffs, [expected_cutoff])

    def test_suspect_missing_extrapolates_from_sample(self) -> None:
        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b", "c", "d"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(warmup_sample=2, activity_probe=lambda persons, cutoff: {"a"}),
        )
        self.assertEqual((row.suspect_missing, row.dormant), (2, 2))
        self.assertIn("suspect_missing extrapolated from sample 2/4", row.notes)
        self.assertEqual(row.verdict, VERDICT_FAIL)

    @parameterized.expand(
        [
            ("loose_threshold_passes", 5.0, VERDICT_PASS),
            ("strict_threshold_fails", 1.0, VERDICT_FAIL),
        ]
    )
    def test_residual_gate_honors_threshold(self, _name: str, threshold: float, expected_verdict: str) -> None:
        # 97 agreeing + 2 residual (new flipped `left` before last_calc) → residual_pct ~2.02%.
        old_members = {f"p{i}" for i in range(99)}
        new_state = _entered([f"p{i}" for i in range(97)], at=NOW - timedelta(hours=2)) | _state(
            {"p97": ("left", NOW - timedelta(hours=2)), "p98": ("left", NOW - timedelta(hours=2))}
        )
        row = classify_cohort(
            screened=_screened(),
            name="x",
            old_members=old_members,
            new_state=new_state,
            last_realtime_calculation_at=NOW - timedelta(minutes=1),
            config=_config(threshold_pct=threshold),
        )
        self.assertEqual((row.residual_old, row.unobserved), (2, 0))
        self.assertGreater(row.residual_pct, 1.0)
        self.assertLess(row.residual_pct, 5.0)
        self.assertEqual(row.verdict, expected_verdict)

    def test_no_classify_gates_on_o_bounded_raw_diff(self) -> None:
        row = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a"},
            new_state=_entered(["b"], at=NOW),
            last_realtime_calculation_at=None,
            config=_config(classify=False, activity_probe=lambda p, c: set(p)),
        )
        self.assertEqual((row.fresh, row.stale, row.suspect_missing), (0, 0, 0))
        self.assertEqual((row.unobserved, row.dormant), (1, 1))  # "a" is outside O, excluded
        self.assertEqual(row.residual_pct, row.raw_diff_pct)
        self.assertEqual(row.verdict, VERDICT_FAIL)

    def test_summarize_counts_verdicts_and_buckets(self) -> None:
        config = _config(activity_probe=lambda persons, cutoff: set(persons))
        rows = [
            classify_cohort(
                screened=_screened(window=30),
                name="warmup",
                old_members={"a", "b"},
                new_state={},
                last_realtime_calculation_at=LAST_CALC,
                config=config,
            ),
            classify_cohort(
                screened=_screened(EXCLUDED_HAS_DROPPED_LEAF),
                name="skip",
                old_members=set(),
                new_state={},
                last_realtime_calculation_at=LAST_CALC,
                config=config,
            ),
            classify_cohort(
                screened=_screened(),
                name="pass",
                old_members={"a"},
                new_state=_entered(["a"], at=NOW),
                last_realtime_calculation_at=LAST_CALC,
                config=config,
            ),
        ]
        summary = summarize(rows, config=config)
        self.assertEqual((summary.passed, summary.failed, summary.warming_up, summary.skipped), (1, 0, 1, 1))
        self.assertEqual((summary.suspect_total, summary.dormant_total, summary.stale_total), (2, 0, 0))
        self.assertEqual(summary.raw_diff_total, 2)
