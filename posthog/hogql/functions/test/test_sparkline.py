from posthog.hogql.errors import HogQLException
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import BaseTest


class TestSparkline(BaseTest):
    def test_sparkline(self):
        response = execute_hogql_query("select sparkline([1,2,3])", self.team)
        self.assertEqual(
            response.clickhouse,
            f"SELECT tuple(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, [1, 2, 3]) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1",
        )
        self.assertEqual(
            response.hogql,
            f"SELECT tuple('__hogql_chart_type', 'sparkline', 'results', [1, 2, 3]) LIMIT 100",
        )
        self.assertEqual(
            response.results[0][0],
            ("__hogql_chart_type", "sparkline", "results", [1, 2, 3]),
        )

    def test_sparkline_error(self):
        with self.assertRaises(HogQLException) as e:
            execute_hogql_query(f"SELECT sparkline()", self.team)
        self.assertEqual(str(e.exception), "Function 'sparkline' expects 1 argument, found 0")
