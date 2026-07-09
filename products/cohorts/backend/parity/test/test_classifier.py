from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

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

    def test_cohort_level_warmup_when_window_exceeds_pipeline_age(self) -> None:
        probe_calls: list[list[str]] = []

        def probe(persons, cutoff):
            probe_calls.append(list(persons))
            return set()

        row = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a", "b", "c"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=probe),
        )
        self.assertEqual(row.verdict, VERDICT_WARMUP)
        self.assertEqual(row.warmup, 3)
        self.assertEqual(row.residual_old, 0)
        self.assertEqual(probe_calls, [])
        self.assertFalse(row.gated)

    def test_warming_cohort_still_gates_on_unexplained_only_new(self) -> None:
        stale_over_inclusion = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a"},
            new_state=_entered(["a"], at=NOW) | _entered(["b"], at=LAST_CALC - timedelta(minutes=5)),
            last_realtime_calculation_at=LAST_CALC,
            config=_config(),
        )
        self.assertEqual(stale_over_inclusion.residual_new, 1)
        self.assertEqual(stale_over_inclusion.verdict, VERDICT_FAIL)

        fresh_only = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a"},
            new_state=_entered(["a"], at=NOW) | _entered(["b"], at=NOW),
            last_realtime_calculation_at=LAST_CALC,
            config=_config(),
        )
        self.assertEqual(fresh_only.residual_new, 0)
        self.assertEqual(fresh_only.verdict, VERDICT_WARMUP)

    def test_person_level_warmup_explains_inactive_only_old(self) -> None:
        seen_cutoffs: list[datetime] = []

        def probe(persons, cutoff):
            seen_cutoffs.append(cutoff)
            return {"active"}

        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"active", "dormant1", "dormant2"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=probe),
        )
        self.assertEqual(row.warmup, 2)
        self.assertEqual(row.residual_old, 1)
        self.assertEqual(seen_cutoffs, [SINCE])
        self.assertEqual(row.verdict, VERDICT_FAIL)

    def test_behavioral_window_narrows_the_warmup_cutoff(self) -> None:
        seen_cutoffs: list[datetime] = []

        def probe(persons, cutoff):
            seen_cutoffs.append(cutoff)
            return set(persons)

        classify_cohort(
            screened=_screened(window=0.25),
            name="x",
            old_members={"a"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(activity_probe=probe),
        )
        self.assertEqual(seen_cutoffs, [NOW - timedelta(days=0.25)])

    def test_warmup_sample_zero_degrades_to_cohort_level_only(self) -> None:
        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(warmup_sample=0, activity_probe=lambda p, c: set()),
        )
        self.assertEqual(row.warmup, 0)
        self.assertEqual(row.residual_old, 2)
        self.assertEqual(row.verdict, VERDICT_FAIL)

    def test_warmup_extrapolates_from_sample(self) -> None:
        row = classify_cohort(
            screened=_screened(window=None),
            name="x",
            old_members={"a", "b", "c", "d"},
            new_state={},
            last_realtime_calculation_at=LAST_CALC,
            config=_config(warmup_sample=2, activity_probe=lambda persons, cutoff: {"a"}),
        )
        self.assertEqual(row.warmup, 2)
        self.assertEqual(row.residual_old, 2)
        self.assertIn("warmup extrapolated from sample 2/4", row.notes)

    def test_residual_gate_threshold(self) -> None:
        old_members = {f"p{i}" for i in range(99)}
        last_calc = NOW - timedelta(minutes=1)
        config = _config(threshold_pct=1.0, activity_probe=lambda p, c: set(p))

        row = classify_cohort(
            screened=_screened(),
            name="x",
            old_members=old_members,
            new_state=_entered([f"p{i}" for i in range(99)], at=NOW - timedelta(hours=2)) | _entered(["q"], at=NOW),
            last_realtime_calculation_at=last_calc,
            config=config,
        )
        self.assertEqual(row.residual_new, 0)
        self.assertEqual(row.fresh, 1)
        self.assertEqual(row.verdict, VERDICT_PASS)

        stale = classify_cohort(
            screened=_screened(),
            name="x",
            old_members=old_members,
            new_state=_entered([f"p{i}" for i in range(97)], at=NOW - timedelta(hours=2)),
            last_realtime_calculation_at=last_calc,
            config=config,
        )
        self.assertGreater(stale.residual_pct, 1.0)
        self.assertEqual(stale.verdict, VERDICT_FAIL)

    def test_no_classify_gates_on_raw_diff(self) -> None:
        row = classify_cohort(
            screened=_screened(window=30),
            name="x",
            old_members={"a"},
            new_state=_entered(["b"], at=NOW),
            last_realtime_calculation_at=None,
            config=_config(classify=False),
        )
        self.assertEqual(row.fresh, 0)
        self.assertEqual(row.warmup, 0)
        self.assertEqual(row.residual_pct, row.raw_diff_pct)
        self.assertEqual(row.verdict, VERDICT_FAIL)

    def test_summarize_counts_verdicts_and_buckets(self) -> None:
        config = _config()
        rows = [
            classify_cohort(
                screened=_screened(window=30),
                name="warm",
                old_members={"a"},
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
        self.assertEqual(summary.warmup_total, 1)
        self.assertEqual(summary.raw_diff_total, 1)
