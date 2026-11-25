import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.accuracy import cost_estimate_accuracy_hogql
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_log_archive import SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE

ARCHIVED_LOG_COMMENTS = {
    "reads_a_and_b": '{"product":"sql_editor","warehouse_table_ids":["table_a","table_b"]}',
    "reads_c": '{"warehouse_table_ids":["table_c"]}',
    "reads_no_table": '{"product":"sql_editor"}',
    "no_log_comment": "",
}


class TestQueryLogTable(ClickhouseTestMixin, APIBaseTest):
    """
    Mostly tests for the optimization of pre-filtering before aggregating. See https://github.com/PostHog/posthog/pull/25604
    """

    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk, enable_select_queries=True)

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_simple_query(self, mock_sync_execute: MagicMock):
        response = execute_hogql_query("select query_start_time from query_log limit 10", self.team)

        ch_query = f"""SELECT
    query_log.query_start_time AS query_start_time
FROM
    (SELECT
        toTimeZone(query_log_archive.query_start_time, %(hogql_val_0)s) AS query_start_time
    FROM
        query_log_archive
    WHERE
        and(equals(query_log_archive.team_id, {self.team.pk}), not(query_log_archive.lc_is_impersonated))) AS query_log
LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, optimize_rewrite_aggregate_function_with_if=0, optimize_min_inequality_conjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0"""

        from unittest.mock import ANY

        mock_sync_execute.assert_called_once_with(
            ch_query,
            {
                "hogql_val_0": "UTC",
            },
            with_column_types=True,
            workload=ANY,
            team_id=self.team.pk,
            readonly=True,
            ch_user=ClickHouseUser.DEFAULT,
            external_tables=None,
        )
        assert response.results is not None

    @parameterized.expand(
        [
            ("has_one_id", "has(warehouse_table_ids, 'table_a')", ["reads_a_and_b"]),
            ("has_any_of_ids", "hasAny(warehouse_table_ids, ['table_b', 'table_c'])", ["reads_a_and_b", "reads_c"]),
            ("has_unknown_id", "has(warehouse_table_ids, 'table_z')", []),
            ("read_any_table", "notEmpty(warehouse_table_ids)", ["reads_a_and_b", "reads_c"]),
            ("read_no_table", "empty(warehouse_table_ids)", ["no_log_comment", "reads_no_table"]),
            ("first_id", "warehouse_table_ids[1] = 'table_c'", ["reads_c"]),
        ]
    )
    def test_filter_on_warehouse_table_ids(self, _name: str, condition: str, expected: list[str]):
        # Rows stay in the archive between cases, so each case tags its own rows.
        tag = uuid.uuid4().hex
        sync_execute(
            f"INSERT INTO {SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE} "
            "(initial_query_start_time, team_id, initial_query_id, lc_client_query_id, lc_is_impersonated, log_comment) VALUES",
            [
                (datetime.now(UTC), self.team.pk, str(uuid.uuid4()), f"{tag}_{name}", False, log_comment)
                for name, log_comment in ARCHIVED_LOG_COMMENTS.items()
            ],
        )

        response = execute_hogql_query(
            f"select query_id from query_log where startsWith(query_id, '{tag}_') and {condition} order by query_id",
            self.team,
        )

        assert [row[0].removeprefix(f"{tag}_") for row in response.results] == expected

    @parameterized.expand([("raw_query_log",), ("query_log",)])
    def test_log_comment_is_not_selectable(self, table: str):
        # log_comment keeps tags such as http_referer, so only the warehouse_table_ids extraction may read it.
        with self.assertRaisesRegex(QueryError, "log_comment"):
            execute_hogql_query(f"select log_comment from {table}", self.team)

    def test_cost_estimate_accuracy_query_runs_against_the_archive(self):
        response = execute_hogql_query(cost_estimate_accuracy_hogql(days=7), self.team)

        assert response.results is not None
        assert response.columns == [
            "plan_fingerprint",
            "queries",
            "median_rows_q_error",
            "p90_rows_q_error",
            "median_bytes_q_error",
            "p90_bytes_q_error",
        ]
