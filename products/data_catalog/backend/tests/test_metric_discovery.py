from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.logic.measure_fingerprint import MeasureExtractionError, extract_measures
from products.data_catalog.backend.logic.metric_discovery import QueryShape, fold_shapes

SIGNUPS = "SELECT count() FROM events WHERE event = 'signup'"


def _digest(query: str) -> str:
    measures = extract_measures(query)
    assert len(measures) == 1, f"expected one measure, got {len(measures)} for: {query}"
    return measures[0].digest


def _shape(query: str, *, users: set[int], days: set[str], runs: int = 1) -> QueryShape:
    return QueryShape(
        sample_hogql=query,
        user_ids=frozenset(users),
        active_days=frozenset(days),
        runs=runs,
    )


class TestMeasureFingerprint(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "different_grain",
                "SELECT count() FROM events WHERE event = 'signup' GROUP BY toDate(timestamp)",
                "SELECT count() FROM events WHERE event = 'signup' GROUP BY properties.country",
            ),
            (
                "different_date_range",
                "SELECT count() FROM events WHERE event = 'signup' AND timestamp > '2026-01-01'",
                "SELECT count() FROM events WHERE event = 'signup' AND timestamp > now() - INTERVAL 7 DAY",
            ),
            (
                "different_order_and_limit",
                "SELECT count() FROM events WHERE event = 'signup' ORDER BY 1 DESC LIMIT 10",
                SIGNUPS,
            ),
            (
                "different_alias",
                "SELECT count() AS signups FROM events WHERE event = 'signup'",
                "SELECT count() AS total FROM events WHERE event = 'signup'",
            ),
            (
                "count_distinct_against_uniq",
                "SELECT count(DISTINCT person_id) FROM events WHERE event = 'signup'",
                "SELECT uniq(person_id) FROM events WHERE event = 'signup'",
            ),
            (
                "uniq_exact_against_uniq",
                "SELECT uniqExact(person_id) FROM events WHERE event = 'signup'",
                "SELECT uniq(person_id) FROM events WHERE event = 'signup'",
            ),
            (
                "count_star_against_count",
                "SELECT count(*) FROM events WHERE event = 'signup'",
                SIGNUPS,
            ),
            (
                "filter_in_subquery",
                "SELECT count() FROM (SELECT * FROM events WHERE event = 'signup')",
                SIGNUPS,
            ),
            (
                "infix_against_function_comparison",
                "SELECT count() FROM events WHERE equals(event, 'signup')",
                SIGNUPS,
            ),
            (
                "conjunct_order",
                "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
                "SELECT count() FROM events WHERE properties.plan = 'pro' AND event = 'signup'",
            ),
        ]
    )
    def test_slice_does_not_change_the_measure(self, _name: str, one: str, other: str) -> None:
        self.assertEqual(_digest(one), _digest(other))

    @parameterized.expand(
        [
            (
                "inverted_filter",
                SIGNUPS,
                "SELECT count() FROM events WHERE event != 'signup'",
            ),
            (
                "different_literal",
                SIGNUPS,
                "SELECT count() FROM events WHERE event = 'login'",
            ),
            (
                "different_table",
                SIGNUPS,
                "SELECT count() FROM persons WHERE event = 'signup'",
            ),
            (
                "extra_conjunct",
                SIGNUPS,
                "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
            ),
            (
                "different_aggregate",
                SIGNUPS,
                "SELECT sum(properties.amount) FROM events WHERE event = 'signup'",
            ),
            (
                "count_column_against_count_star",
                "SELECT count(properties.plan) FROM events WHERE event = 'signup'",
                "SELECT count(*) FROM events WHERE event = 'signup'",
            ),
        ]
    )
    def test_identity_change_splits_the_measure(self, _name: str, one: str, other: str) -> None:
        self.assertNotEqual(_digest(one), _digest(other))

    def test_each_aggregate_in_the_projection_is_its_own_measure(self) -> None:
        measures = extract_measures("SELECT count(), uniq(person_id) FROM events WHERE event = 'signup'")

        self.assertEqual(len(measures), 2)
        self.assertEqual({measure.aggregate for measure in measures}, {"count()", "uniq(person_id)"})

    def test_a_ratio_of_two_aggregates_is_one_measure(self) -> None:
        measures = extract_measures("SELECT count() / uniq(person_id) FROM events WHERE event = 'signup'")

        self.assertEqual(len(measures), 1)

    def test_a_query_without_an_aggregate_yields_no_measure(self) -> None:
        self.assertEqual(extract_measures("SELECT event FROM events LIMIT 10"), [])

    def test_unparseable_text_is_an_error_not_an_empty_result(self) -> None:
        with self.assertRaises(MeasureExtractionError):
            extract_measures("SELECT count( FROM WHERE")

    @parameterized.expand(
        [
            ("saved_query_variable", "SELECT count() FROM events WHERE properties.org = {variables.org_id}"),
            ("dashboard_filter", "SELECT count() FROM events WHERE event = 'signup' AND {filters}"),
        ]
    )
    def test_a_placeholder_yields_a_measure_instead_of_raising(self, _name: str, query: str) -> None:
        measures = extract_measures(query)

        self.assertEqual(len(measures), 1)
        self.assertEqual(measures[0].aggregate, "count()")

    def test_evidence_reads_as_a_sentence(self) -> None:
        measure = extract_measures(SIGNUPS)[0]

        self.assertEqual(measure.describe(), "count() on events where event = 'signup'")


class TestFoldShapes(SimpleTestCase):
    def test_users_are_unioned_across_shapes_not_added(self) -> None:
        shapes = [
            _shape(SIGNUPS, users={1, 2}, days={"2026-08-01"}),
            _shape(
                "SELECT count() FROM events WHERE event = 'signup' GROUP BY toDate(timestamp)",
                users={2, 3},
                days={"2026-08-02"},
            ),
        ]

        scan = fold_shapes(shapes)

        self.assertEqual(len(scan.candidates), 1)
        self.assertEqual(scan.candidates[0].distinct_users, 3)
        self.assertEqual(scan.candidates[0].shape_count, 2)

    def test_a_measure_one_person_runs_stays_below_the_bar(self) -> None:
        shapes = [_shape(SIGNUPS, users={7}, days={"2026-08-01", "2026-08-02"}, runs=400)]

        scan = fold_shapes(shapes)

        self.assertEqual(scan.candidates, ())
        self.assertEqual(scan.measures_below_bar, 1)

    def test_unparsed_shapes_are_counted_apart_from_shapes_without_an_aggregate(self) -> None:
        shapes = [
            _shape("SELECT count( FROM WHERE", users={1, 2}, days={"2026-08-01"}),
            _shape("SELECT event FROM events", users={1, 2}, days={"2026-08-01"}),
            _shape(SIGNUPS, users={1, 2}, days={"2026-08-01"}),
        ]

        scan = fold_shapes(shapes)

        self.assertEqual(scan.shapes_read, 3)
        self.assertEqual(scan.shapes_unparsed, 1)
        self.assertEqual(scan.shapes_without_aggregate, 1)
        self.assertAlmostEqual(scan.parse_rate, 2 / 3)

    def test_candidates_are_ranked_by_how_many_people_ran_them(self) -> None:
        shapes = [
            _shape(SIGNUPS, users={1, 2}, days={"2026-08-01"}),
            _shape("SELECT count() FROM events WHERE event = 'login'", users={1, 2, 3, 4}, days={"2026-08-01"}),
        ]

        scan = fold_shapes(shapes)

        self.assertEqual(
            [candidate.distinct_users for candidate in scan.candidates],
            [4, 2],
        )
