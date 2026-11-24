from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.query_complexity import Complexity, measure_complexity, query_complexity


class TestQueryComplexity(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_event_count", "SELECT count() FROM events WHERE event = 'x'", Complexity.LOW),
            ("rounded_sum_on_a_view", "SELECT month, round(sum(mrr)) FROM summary GROUP BY month", Complexity.LOW),
            ("conditional_counts", "SELECT countIf(a = 1), countIf(b = 2) FROM t", Complexity.MEDIUM),
            ("ratio_of_aggregates", "SELECT sumIf(x, a = 1) / sum(x) FROM t", Complexity.MEDIUM),
            ("one_join", "SELECT count() FROM a JOIN b ON a.id = b.id", Complexity.MEDIUM),
            (
                "cte_with_a_join_and_a_ratio",
                "WITH c AS (SELECT id, sum(x) AS s FROM t GROUP BY id) "
                "SELECT sum(c.s) / count() FROM c JOIN d ON c.id = d.id",
                Complexity.HIGH,
            ),
            (
                "window_over_a_subquery",
                "SELECT m, s - lagInFrame(s) OVER (ORDER BY m) FROM (SELECT m, sum(x) AS s FROM t GROUP BY m)",
                Complexity.HIGH,
            ),
            ("does_not_parse", "SELECT FROM WHERE", Complexity.UNKNOWN),
        ]
    )
    def test_query_complexity(self, _name: str, sql: str, expected: Complexity) -> None:
        assert query_complexity(sql) == expected

    @parameterized.expand(
        [
            (
                "plain_count_inside_a_large_query",
                "WITH a AS (SELECT count() AS c FROM events WHERE event = 'x') "
                "SELECT c, lagInFrame(c) OVER (ORDER BY c) FROM a JOIN b ON 1 = 1",
                Complexity.LOW,
            ),
            ("ratio_with_conditions", "SELECT sumIf(x, a = 1) / sum(x) FROM t WHERE b = 2", Complexity.MEDIUM),
            (
                "join_with_conditions_and_filters",
                "SELECT countIf(p.plan = 'pro') / count() FROM events e JOIN persons p ON e.person_id = p.id "
                "WHERE e.event = 'x' AND p.country = 'US' AND e.properties.paid = true",
                Complexity.HIGH,
            ),
        ]
    )
    def test_measure_complexity(self, _name: str, sql: str, expected: Complexity) -> None:
        assert measure_complexity(extract_measures(sql)[0]) == expected
