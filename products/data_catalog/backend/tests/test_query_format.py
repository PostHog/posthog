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
        ]
    )
    def test_readable_sql(self, _name: str, sql: str, expected: str) -> None:
        assert readable_sql(sql) == expected
