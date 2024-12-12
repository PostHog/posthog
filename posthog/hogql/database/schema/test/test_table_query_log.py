from unittest.mock import MagicMock, patch
from posthog.clickhouse.client import sync_execute
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)


class TestPersonOptimization(ClickhouseTestMixin, APIBaseTest):
    """
    Mostly tests for the optimization of pre-filtering before aggregating. See https://github.com/PostHog/posthog/pull/25604
    """

    def setUp(self):
        super().setUp()
        self.database = create_hogql_database(self.team.pk)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk, enable_select_queries=True)

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_dumb_query(self, mock_sync_execute: MagicMock):
        response = execute_hogql_query("select query_start_time from query_log limit 10", self.team)

        ch_query = f"""SELECT
    query_log.query_start_time AS query_start_time
FROM
    (SELECT
        toTimeZone(raw_query_log.event_time, %(hogql_val_0)s) AS query_start_time
    FROM
        clusterAllReplicas(posthog, system.query_log) AS raw_query_log
    WHERE
        and(ifNull(equals({self.team.pk}, JSONExtractInt(raw_query_log.log_comment, %(hogql_val_1)s)), 0), in(raw_query_log.type, [%(hogql_val_2)s, %(hogql_val_3)s, %(hogql_val_4)s]), raw_query_log.is_initial_query)) AS query_log
LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0"""

        from unittest.mock import ANY

        mock_sync_execute.assert_called_once_with(
            ch_query,
            {
                "hogql_val_0": "UTC",
                "hogql_val_1": "user_id",
                "hogql_val_2": "QueryFinish",
                "hogql_val_3": "ExceptionBeforeStart",
                "hogql_val_4": "ExceptionWhileProcessing",
            },
            with_column_types=True,
            workload=ANY,
            team_id=self.team.pk,
            readonly=True,
        )
        assert response.results is not None
