from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.logic.query_format import readable_sql


class TestReadableSql(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "lays_out_clauses_and_keeps_name_case",
                "SELECT month, sum(mrr) FROM events WHERE event = 'x' GROUP BY month",
                "SELECT month,\n       sum(mrr)\nFROM events\nWHERE event = 'x'\nGROUP BY month",
            ),
            (
                "keeps_a_placeholder",
                "SELECT count() FROM events WHERE {filters} AND event = 'x'",
                "SELECT count()\nFROM events\nWHERE {filters}\n    AND event = 'x'",
            ),
            (
                "very_long_query_stays_as_written",
                "SELECT " + "a, " * 7000 + "b FROM t",
                "SELECT " + "a, " * 7000 + "b FROM t",
            ),
            (
                "nesting_too_deep_for_the_formatter_stays_as_written",
                "SELECT " + "coalesce(" * 300 + "x" + ")" * 300 + " FROM t",
                "SELECT " + "coalesce(" * 300 + "x" + ")" * 300 + " FROM t",
            ),
            (
                "a_value_list_that_layout_would_blow_up_stays_as_written",
                "SELECT count() FROM events WHERE tuple(a, b) IN ("
                + ", ".join(f"('v{i}', {i})" for i in range(400))
                + ")",
                "SELECT count() FROM events WHERE tuple(a, b) IN ("
                + ", ".join(f"('v{i}', {i})" for i in range(400))
                + ")",
            ),
            (
                "a_short_query_may_double_in_length",
                "SELECT a, b, c, d, e, f, g FROM t",
                "SELECT a,\n       b,\n       c,\n       d,\n       e,\n       f,\n       g\nFROM t",
            ),
        ]
    )
    def test_readable_sql(self, _name: str, sql: str, expected: str) -> None:
        assert readable_sql(sql) == expected
