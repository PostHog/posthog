import subprocess

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.batch import BatchQueryResult, CountBatchPlanner
from posthog.hogql.scripts.batch_demo import SyntheticClickHouse, compare_results, execute_plan


class TestBatchDemo(SimpleTestCase):
    def test_execution_error_preserves_query_id_and_server_message(self) -> None:
        plan = CountBatchPlanner().plan({"broken": "SELECT * FROM events"})
        runner = SyntheticClickHouse(container="test-clickhouse", rows=10)
        response = subprocess.CompletedProcess(args=[], returncode=130, stdout="", stderr="Code: 386. NO_COMMON_TYPE")
        with patch("posthog.hogql.scripts.batch_demo.subprocess.run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, r"Query \[broken\] failed: Code: 386. NO_COMMON_TYPE"):
                execute_plan(plan, runner)

    @parameterized.expand(
        [
            ("unordered", "SELECT event FROM events", ((2,), (1,), (1,)), True),
            ("ordered", "SELECT event FROM events ORDER BY event", ((2,), (1,), (1,)), False),
            ("duplicates", "SELECT event FROM events", ((1,), (2,)), False),
        ]
    )
    def test_comparison_preserves_order_and_multiplicity(
        self, _name: str, sql: str, rows: tuple[tuple[object, ...], ...], matches: bool
    ) -> None:
        baseline = BatchQueryResult(columns=("event",), types=("UInt64",), rows=((1,), (1,), (2,)))
        combined = BatchQueryResult(columns=baseline.columns, types=baseline.types, rows=rows)
        self.assertEqual(compare_results(sql, baseline, combined), matches)
