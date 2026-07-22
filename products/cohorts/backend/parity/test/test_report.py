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
from products.cohorts.backend.parity.report import format_notes, format_reconcile_notes, to_json


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
