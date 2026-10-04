from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.population import compare_populations, skip_population, summarize_population

CALCULATED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _compare(fold: set[str], legacy: set[str], *, cohort_id: int = 10, with_ids: bool = False):
    return compare_populations(
        cohort_id=cohort_id,
        name=f"c{cohort_id}",
        fold_members=fold,
        legacy_members=legacy,
        legacy_version=3,
        calculated_at=CALCULATED_AT,
        with_ids=with_ids,
    )


class TestPopulation(SimpleTestCase):
    @parameterized.expand(
        [
            ("identical", {"a", "b"}, {"a", "b"}, 2, 0, 0, 100.0),
            # A cohort neither side has anyone in is total agreement, not a ZeroDivisionError.
            ("both_empty", set(), set(), 0, 0, 0, 100.0),
            ("fold_only", {"a", "b"}, set(), 0, 2, 0, 0.0),
            ("legacy_only", set(), {"a"}, 0, 0, 1, 0.0),
            ("partial_overlap", {"a", "b"}, {"b", "c"}, 1, 1, 1, 100 / 3),
            ("fold_superset", {"a", "b"}, {"a"}, 1, 1, 0, 50.0),
        ]
    )
    def test_set_shapes_score_over_the_union(
        self,
        _name: str,
        fold: set[str],
        legacy: set[str],
        both: int,
        only_fold: int,
        only_legacy: int,
        match_pct: float,
    ) -> None:
        row = _compare(fold, legacy)
        self.assertEqual(
            (row.fold_count, row.legacy_count, row.both, row.only_fold, row.only_legacy),
            (len(fold), len(legacy), both, only_fold, only_legacy),
        )
        self.assertAlmostEqual(row.match_pct, match_pct)

    def test_divergent_ids_ship_complete_only_when_asked(self) -> None:
        # The flag exists so an operator can look a person up in the seeder's output; a sampled or
        # truncated list would not answer that, and shipping ids by default would dump the whole diff.
        default = _compare({"b", "a"}, {"a", "c"})
        self.assertEqual((default.only_fold_ids, default.only_legacy_ids), ((), ()))

        with_ids = _compare({"b", "a"}, {"a", "c"}, with_ids=True)
        self.assertEqual(with_ids.only_fold_ids, ("b",))
        self.assertEqual(with_ids.only_legacy_ids, ("c",))

    def test_summary_totals_ignore_skipped_rows_and_weight_by_person(self) -> None:
        # Averaging per-row percentages would let a 2-person cohort outvote a 200-person one, and a
        # skipped cohort counted as agreement would hide the fact that it has no oracle at all.
        rows = [
            _compare({f"p{i}" for i in range(200)}, {f"p{i}" for i in range(100)}, cohort_id=1),
            _compare({"a"}, {"a"}, cohort_id=2),
            skip_population(cohort_id=3, name="c3", reason="never_calculated"),
        ]
        summary = summarize_population(rows)
        self.assertEqual((summary.compared, summary.skipped), (2, 1))
        self.assertEqual((summary.fold_total, summary.legacy_total), (201, 101))
        self.assertEqual((summary.both_total, summary.only_fold_total, summary.only_legacy_total), (101, 100, 0))
        assert summary.match_pct is not None
        self.assertAlmostEqual(summary.match_pct, 101 / 201 * 100)

    def test_all_skipped_run_has_no_match_pct(self) -> None:
        # A single --cohort-id run whose only row skips would otherwise serialize the all-zero totals
        # as a perfect 100.0 next to "compared": 0, and a JSON reader keying on the summary would
        # read "no oracle anywhere" as agreement.
        row = skip_population(cohort_id=3, name="c3", reason="last_calculation_before_since")
        self.assertIsNone(row.match_pct)
        summary = summarize_population([row])
        self.assertEqual((summary.compared, summary.skipped), (0, 1))
        self.assertIsNone(summary.match_pct)
