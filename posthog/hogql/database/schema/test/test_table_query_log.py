import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.accuracy import cost_estimate_accuracy_hogql
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser


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

    def test_cost_estimate_accuracy_query_runs_against_the_archive(self) -> None:
        for fingerprint, estimated_bytes, read_bytes, status, initial in [
            ("rows-only", None, 0, "QueryFinish", 1),
            ("mixed", None, 500, "QueryFinish", 1),
            ("mixed", 2000, 500, "QueryFinish", 1),
            ("mixed", 2000, 0, "QueryFinish", 1),
            ("mixed", 0, 500, "QueryFinish", 1),
            ("excluded", 2000, 500, "ExceptionWhileProcessing", 1),
            ("excluded", 2000, 500, "QueryFinish", 0),
        ]:
            tags: dict[str, str | int] = {
                "team_id": self.team.pk,
                "plan_fingerprint": fingerprint,
                "estimated_rows": 100,
            }
            if estimated_bytes is not None:
                tags["estimated_bytes"] = estimated_bytes
            sync_execute(
                "INSERT INTO sharded_query_log_archive "
                "(event_date, event_time, team_id, type, is_initial_query, read_rows, read_bytes, log_comment) "
                "VALUES (today(), now(), %(team_id)s, %(status)s, %(initial)s, 50, %(read_bytes)s, %(tags)s)",
                {
                    "team_id": self.team.pk,
                    "status": status,
                    "initial": initial,
                    "read_bytes": read_bytes,
                    "tags": json.dumps(tags),
                },
            )
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
        assert {row[0]: row[1:] for row in response.results} == {
            "rows-only": (1, 2.0, 2.0, None, None),
            "mixed": (4, 2.0, 2.0, 4.0, 4.0),
        }
