from django.test import SimpleTestCase

from products.cohorts.backend.parity.classifier import (
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    VERDICT_WARMUP,
    AggregateSummary,
    CohortComparison,
)
from products.cohorts.backend.parity.fold import ReconcileRunCompleteness
from products.cohorts.backend.parity.recompute import RecomputeComparison, RecomputeSummary
from products.cohorts.backend.parity.report import (
    format_notes,
    format_recompute_table,
    format_reconcile_notes,
    to_json,
    to_recompute_json,
)


def _row(
    cohort_id: int,
    verdict: str,
    residual_pct: float = 0.0,
    notes: tuple[str, ...] = (),
) -> CohortComparison:
    return CohortComparison(
        cohort_id=cohort_id,
        name=f"c{cohort_id}",
        eligibility="single_leaf",
        verdict=verdict,
        residual_pct=residual_pct,
        notes=notes,
    )


class TestReport(SimpleTestCase):
    def test_json_rows_order_failures_first(self) -> None:
        rows = [
            _row(1, VERDICT_SKIP),
            _row(2, VERDICT_PASS),
            _row(3, VERDICT_FAIL, residual_pct=1.0),
            _row(4, VERDICT_WARMUP),
            _row(5, VERDICT_FAIL, residual_pct=9.0),
        ]
        document = to_json(rows, AggregateSummary(), {"team_id": 2})
        self.assertEqual(
            [(r["cohort_id"], r["verdict"]) for r in document["cohorts"]],
            [(5, VERDICT_FAIL), (3, VERDICT_FAIL), (4, VERDICT_WARMUP), (2, VERDICT_PASS), (1, VERDICT_SKIP)],
        )
        self.assertEqual(document["meta"], {"team_id": 2})

    def test_reconcile_completeness_is_rendered_as_complete_or_partial_notes(self) -> None:
        notes = format_reconcile_notes(
            [
                ReconcileRunCompleteness(run_id="run-b", cohort_id=10, partitions_seen=41),
                ReconcileRunCompleteness(run_id="run-a", cohort_id=10, partitions_seen=64),
            ]
        )

        self.assertEqual(notes, ("reconcile run run-a: 64/64", "reconcile run run-b: partial 41/64"))
        row = _row(10, VERDICT_PASS, notes=notes)
        self.assertEqual(
            format_notes([row]),
            "  cohort 10: reconcile run run-a: 64/64\n  cohort 10: reconcile run run-b: partial 41/64",
        )
        document = to_json([row], AggregateSummary(), {"team_id": 2})
        self.assertEqual(document["cohorts"][0]["notes"], notes)


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
