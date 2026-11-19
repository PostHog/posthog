from django.test import SimpleTestCase

from products.cohorts.backend.parity.fold import ReconcileRunCompleteness
from products.cohorts.backend.parity.population import PopulationComparison, PopulationSummary, skip_population
from products.cohorts.backend.parity.recompute import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    RecomputeComparison,
    RecomputeSummary,
)
from products.cohorts.backend.parity.report import (
    format_population_table,
    format_recompute_table,
    to_population_json,
    to_recompute_json,
)


def _population_row(cohort_id: int, *, match_pct: float, fold_count: int = 0) -> PopulationComparison:
    return PopulationComparison(
        cohort_id=cohort_id,
        name=f"c{cohort_id}",
        compared=True,
        match_pct=match_pct,
        fold_count=fold_count,
    )


class TestRecomputeReport(SimpleTestCase):
    def test_recompute_json_carries_every_decay_watch_field(self) -> None:
        row = RecomputeComparison(
            cohort_id=433564,
            name="canary",
            supported=True,
            verdict=VERDICT_PASS,
            fold_count=5303,
            oracle_count=5933,
            both=5303,
            missing=630,
            missing_boundary_day=630,
            expires_by_day={"2026-07-31": 630},
            samples={"missing_boundary_day": ("0199-aaaa", "0199-bbbb")},
            run_id="run-1",
            run_status="seeding",
            boundary_at="2026-07-24T02:23:00+00:00",
            boundary_day="2026-07-23",
            run_timezone="US/Pacific",
            chunk_days_confirmed=21,
            shape_hash_drift=False,
            reconcile_runs=(ReconcileRunCompleteness(run_id="run-1", cohort_id=433564, partitions_seen=64),),
        )
        meta = {"oracle": "recompute", "at": "2026-07-24T18:00:00+00:00", "grace_minutes": 10, "run_id": "run-1"}
        document = to_recompute_json([row], RecomputeSummary(passed=1), meta)

        self.assertEqual({"oracle", "at", "grace_minutes", "run_id"}, set(document["meta"]))
        cohort = document["cohorts"][0]
        # The decay-watch contract: every field a daily watch needs must survive serialization.
        for field in (
            "run_id",
            "run_status",
            "boundary_at",
            "boundary_day",
            "run_timezone",
            "chunk_days_confirmed",
            "shape_hash_drift",
            "reconcile_runs",
            "expires_by_day",
            "false_hard",
            "eviction_pending",
            "missing_boundary_day",
        ):
            self.assertIn(field, cohort)
        self.assertEqual(cohort["expires_by_day"], {"2026-07-31": 630})
        self.assertEqual(cohort["reconcile_runs"][0]["partitions_seen"], 64)
        # The caveats promise person ids for triage, so they have to survive serialization.
        self.assertEqual(cohort["samples"], {"missing_boundary_day": ("0199-aaaa", "0199-bbbb")})

    def test_recompute_json_orders_failures_first(self) -> None:
        rows = [
            RecomputeComparison(cohort_id=1, name="a", supported=True, verdict=VERDICT_PASS),
            RecomputeComparison(cohort_id=2, name="b", supported=False, verdict=VERDICT_SKIP),
            RecomputeComparison(cohort_id=3, name="c", supported=True, verdict=VERDICT_FAIL, false_hard=2),
        ]
        document = to_recompute_json(rows, RecomputeSummary(), {})
        self.assertEqual([c["cohort_id"] for c in document["cohorts"]], [3, 1, 2])

    def test_recompute_table_columns_line_up_across_row_kinds(self) -> None:
        # A screen-skipped row spends the numeric columns on its reason; sizing that field by hand
        # drifts from the header the moment a column is added or renamed.
        rows = [
            RecomputeComparison(cohort_id=1, name="numeric", supported=True, verdict=VERDICT_PASS, fold_count=5303),
            RecomputeComparison(
                cohort_id=2,
                name="x" * 60,
                supported=False,
                verdict=VERDICT_SKIP,
                skip_reason="has_event_property_filters",
            ),
        ]
        lines = format_recompute_table(rows).split("\n")
        self.assertEqual({len(line) for line in lines}, {len(lines[0])})
        self.assertIn("SKIP: has_event_property_filters", lines[-1])

    def test_population_table_columns_line_up_across_row_kinds(self) -> None:
        rows = [
            _population_row(1, match_pct=99.5, fold_count=5303),
            skip_population(cohort_id=2, name="x" * 60, reason="never_calculated"),
        ]
        lines = format_population_table(rows).split("\n")
        self.assertEqual({len(line) for line in lines}, {len(lines[0])})
        self.assertIn("SKIP: never_calculated", lines[-1])

    def test_population_rows_order_worst_agreement_first(self) -> None:
        # The report has no verdict to sort on, so a sign flip here would put the healthiest cohorts
        # at the top of a long table and bury the divergent ones an operator is looking for.
        rows = [
            _population_row(1, match_pct=100.0),
            skip_population(cohort_id=2, name="c2", reason="never_calculated"),
            _population_row(3, match_pct=12.0),
            _population_row(4, match_pct=61.5),
        ]
        document = to_population_json(rows, PopulationSummary(), {})
        self.assertEqual([c["cohort_id"] for c in document["cohorts"]], [3, 4, 1, 2])
