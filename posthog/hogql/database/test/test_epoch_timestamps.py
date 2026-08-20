from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.epoch_timestamps import epoch_to_datetime_expr, is_integer_clickhouse_type
from posthog.hogql.query import execute_hogql_query


class TestEpochTimestamps(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("int64", "Int64", True),
            ("uint32", "UInt32", True),
            ("nullable_int64", "Nullable(Int64)", True),
            ("datetime", "DateTime64(3, 'UTC')", False),
            ("nullable_string", "Nullable(String)", False),
            ("interval", "IntervalSecond", False),
            ("none", None, False),
        ]
    )
    def test_is_integer_clickhouse_type(self, _name: str, clickhouse_type: str | None, expected: bool) -> None:
        assert is_integer_clickhouse_type(clickhouse_type) is expected

    def test_epoch_to_datetime_expr_reads_each_unit_as_the_same_instant(self) -> None:
        seconds = 1_762_419_600  # 2025-11-06 09:00:00 UTC
        select = ast.SelectQuery(
            select=[
                ast.Call(
                    name="toUnixTimestamp",
                    args=[epoch_to_datetime_expr(ast.Constant(value=seconds * scale))],
                )
                for scale in (1, 10**3, 10**6, 10**9)
            ]
        )
        response = execute_hogql_query(query=select, team=self.team)
        assert response.results == [(seconds, seconds, seconds, seconds)]
