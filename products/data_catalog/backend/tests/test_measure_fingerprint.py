from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.logic.measure_fingerprint import MeasureExtractionError, extract_measures

SIGNUPS = "SELECT count() FROM events WHERE event = 'signup'"


def _digest(query: str) -> str:
    measures = extract_measures(query)
    assert len(measures) == 1, f"expected one measure, got {len(measures)} for: {query}"
    return measures[0].digest


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
                "relative_date_on_a_column_with_any_name",
                "SELECT sum(mrr) FROM summary WHERE plan = 'pro' AND closes < toStartOfMonth(today())",
                "SELECT sum(mrr) FROM summary WHERE plan = 'pro' AND period_end >= now() - INTERVAL 1 MONTH",
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
            (
                "and_function_against_and_operator",
                "SELECT count() FROM events WHERE and(event = 'signup', properties.plan = 'pro')",
                "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'",
            ),
            (
                "aggregate_in_cte",
                "WITH daily AS (SELECT toDate(timestamp) AS day, count() AS c FROM events WHERE event = 'signup' "
                "GROUP BY day) SELECT day, c FROM daily ORDER BY day",
                SIGNUPS,
            ),
            (
                "aggregate_in_subquery",
                "SELECT day, c FROM (SELECT toDate(timestamp) AS day, count() AS c FROM events "
                "WHERE event = 'signup' GROUP BY day)",
                SIGNUPS,
            ),
            (
                "cte_reads_another_cte",
                "WITH s AS (SELECT * FROM events WHERE event = 'signup'), d AS (SELECT count() AS c FROM s) "
                "SELECT c FROM d",
                SIGNUPS,
            ),
            (
                "union_branches_join_with_or",
                "SELECT count() FROM (SELECT * FROM events WHERE event = 'a' AND timestamp > now() "
                "UNION ALL SELECT * FROM events WHERE event = 'b')",
                "SELECT count() FROM events WHERE event = 'a' OR event = 'b'",
            ),
            (
                "three_cte_pass_through",
                "WITH a AS (SELECT * FROM events), b AS (SELECT * FROM a), c AS (SELECT * FROM b) "
                "SELECT count() FROM c WHERE event = 'signup'",
                SIGNUPS,
            ),
            (
                "cte_named_after_its_base_table",
                "WITH events AS (SELECT * FROM events WHERE event = 'signup') SELECT count() FROM events",
                SIGNUPS,
            ),
            (
                "table_alias_prefix",
                "SELECT count() FROM events e WHERE e.event = 'signup'",
                SIGNUPS,
            ),
            (
                "outer_filter_on_an_aggregated_value",
                "WITH d AS (SELECT properties.plan AS plan, count() AS c FROM events WHERE event = 'signup' "
                "GROUP BY plan) SELECT plan, c FROM d WHERE c > 100",
                SIGNUPS,
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
            (
                "outer_filter_on_an_inner_aggregate",
                SIGNUPS,
                "WITH d AS (SELECT properties.plan AS plan, count() AS c FROM events WHERE event = 'signup' "
                "GROUP BY plan) SELECT c FROM d WHERE plan = 'pro'",
            ),
            (
                "inner_against_left_join",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id",
                "SELECT count() FROM events e LEFT JOIN persons p ON e.person_id = p.id",
            ),
            (
                "different_join_condition",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id",
                "SELECT count() FROM events e JOIN persons p ON e.distinct_id = p.id",
            ),
            (
                "or_with_a_time_condition",
                "SELECT count() FROM events WHERE event = 'signup' OR timestamp > now() - INTERVAL 1 DAY",
                "SELECT count() FROM events",
            ),
            (
                "count_null_against_count",
                "SELECT count(NULL) FROM events",
                "SELECT count() FROM events",
            ),
            (
                "prewhere_filter",
                "SELECT count() FROM events PREWHERE event = 'signup'",
                "SELECT count() FROM events",
            ),
            (
                "different_computed_column_in_a_source",
                "SELECT sum(x) FROM (SELECT properties.a AS x FROM events)",
                "SELECT sum(x) FROM (SELECT properties.b AS x FROM events)",
            ),
            (
                "relative_date_inside_a_subquery_filter",
                "SELECT count() FROM events WHERE event = 'signup' "
                "AND person_id IN (SELECT id FROM persons WHERE created_at > now() - INTERVAL 7 DAY)",
                SIGNUPS,
            ),
            (
                "duration_filter_on_time_columns",
                "SELECT count() FROM sessions WHERE dateDiff('second', started_at, ended_at) > 600",
                "SELECT count() FROM sessions",
            ),
            (
                "alias_prefix_in_a_join",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id WHERE p.properties.plan = 'pro'",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id WHERE e.properties.plan = 'pro'",
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

    @parameterized.expand(
        [
            ("plain_rows", "SELECT event FROM events LIMIT 10"),
            ("scalar_subquery", "SELECT (SELECT count() FROM events) FROM persons"),
        ]
    )
    def test_a_query_without_an_aggregate_yields_no_measure(self, _name: str, query: str) -> None:
        self.assertEqual(extract_measures(query), [])

    @parameterized.expand(
        [
            ("unparseable_text", "SELECT count( FROM WHERE"),
            ("distinct_source", "SELECT count() FROM (SELECT DISTINCT person_id FROM events)"),
            ("grouped_source", "SELECT count() FROM (SELECT person_id FROM events GROUP BY person_id)"),
            (
                "having_source",
                "SELECT count() FROM (SELECT person_id FROM events GROUP BY person_id HAVING count() > 1)",
            ),
            ("limited_source", "SELECT count() FROM (SELECT * FROM events LIMIT 10)"),
            ("aggregated_source", "SELECT count() FROM (SELECT count() FROM events)"),
            (
                "deduplicating_union_source",
                "SELECT count() FROM (SELECT person_id FROM events UNION DISTINCT SELECT person_id FROM events)",
            ),
            ("array_join", "SELECT count() FROM events ARRAY JOIN [1, 2] AS n"),
            ("table_function_source", "SELECT count() FROM numbers(10)"),
            ("sampled_source", "SELECT count() FROM events SAMPLE 0.1 WHERE event = 'signup'"),
            (
                "cte_chain_past_the_depth_limit",
                "WITH a AS (SELECT * FROM events), b AS (SELECT * FROM a), c AS (SELECT * FROM b), "
                "d AS (SELECT * FROM c), e AS (SELECT * FROM d), f AS (SELECT * FROM e) SELECT count() FROM f",
            ),
            (
                "pass_through_chain_past_the_depth_limit",
                "SELECT c FROM (SELECT c FROM (SELECT c FROM (SELECT c FROM (SELECT c FROM "
                "(SELECT c FROM (SELECT count() AS c FROM events))))))",
            ),
            (
                "cte_fan_out",
                "WITH c0 AS (SELECT * FROM events), "
                + ", ".join(
                    f"c{level} AS (SELECT * FROM {' CROSS JOIN '.join([f'c{level - 1}'] * 10)})" for level in (1, 2, 3)
                )
                + " SELECT count() FROM "
                + " CROSS JOIN ".join(["c3"] * 10),
            ),
        ]
    )
    def test_a_query_the_fingerprint_cannot_express_is_an_error_not_an_empty_result(
        self, _name: str, query: str
    ) -> None:
        with self.assertRaises(MeasureExtractionError):
            extract_measures(query)

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
