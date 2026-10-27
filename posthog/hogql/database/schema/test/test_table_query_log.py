from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.accuracy import cost_estimate_accuracy_hogql
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_metadata import PropertyMetadata
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser


@override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False)
class TestPrivateQueryLogVisibility(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{name}_{team_id}", query, scans, team_id)
            for name, query, scans in [
                ("friendly", "SELECT query_id FROM query_log", 1),
                ("raw", "SELECT query_id FROM raw_query_log", 1),
                ("alias", "SELECT q.query_id FROM raw_query_log AS q", 1),
                (
                    "join",
                    "SELECT a.query_id FROM raw_query_log a LEFT JOIN raw_query_log b ON a.query_id = b.query_id",
                    2,
                ),
                ("subquery", "SELECT * FROM (SELECT query_id FROM raw_query_log)", 1),
            ]
            for team_id in (2, 123)
        ]
    )
    def test_only_trial_project_scans_exclude_private_activity(
        self, _name: str, query: str, scans: int, team_id: int
    ) -> None:
        with patch("posthog.hogql.transforms.property_types.load_property_metadata", return_value=PropertyMetadata()):
            sql, _ = prepare_and_print_ast(
                parse_select(query),
                HogQLContext(
                    team_id=team_id,
                    database=Database(),
                    enable_select_queries=True,
                    restricted_properties=set(),
                    use_new_events_schema=False,
                ),
                "clickhouse",
            )
        self.assertEqual(
            sql.count("NOT ifNull(dynamicElement(log_comment.is_scout_experiment, 'Bool'), false)"),
            scans if team_id == 2 else 0,
        )
        if team_id != 2:
            self.assertNotIn("asterisk_include_alias_columns", sql)
        self.assertIn(f"team_id, {team_id}", sql)


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

        table_ref = "query_log_archive"
        if self.team.pk == 2:
            table_ref = (
                "(SELECT * FROM query_log_archive WHERE NOT ifNull(dynamicElement(log_comment.is_scout_experiment, 'Bool'), false) "
                "SETTINGS asterisk_include_alias_columns = 1) AS query_log_archive"
            )
        ch_query = f"""SELECT
    query_log.query_start_time AS query_start_time
FROM
    (SELECT
        toTimeZone(query_log_archive.query_start_time, %(hogql_val_0)s) AS query_start_time
    FROM
        {table_ref}
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
        now = datetime.now(UTC)
        # The archive keeps rows across tests, including the ones query execution logs for this team, so the
        # fingerprints are unique to this run and the result is read for them only.
        marker = uuid4().hex
        # The archive stores 0 for a byte estimate that was never recorded.
        rows = [
            ("rows-only", 0, 0, "QueryFinish", 1),
            ("mixed", 0, 500, "QueryFinish", 1),
            ("mixed", 2000, 500, "QueryFinish", 1),
            ("mixed", 2000, 0, "QueryFinish", 1),
            ("mixed", 0, 500, "QueryFinish", 1),
            ("excluded", 2000, 500, "ExceptionWhileProcessing", 1),
            ("excluded", 2000, 500, "QueryFinish", 0),
        ]
        sync_execute(
            """INSERT INTO sharded_query_log_archive_v3
            (initial_query_start_time, team_id, initial_query_id, is_initial_query, type, event_time_microseconds,
             read_rows, read_bytes, lc_plan_fingerprint, lc_estimated_rows, lc_estimated_bytes) VALUES""",
            [
                (
                    now,
                    self.team.pk,
                    f"{marker}-{i}",
                    initial,
                    status,
                    now,
                    50,
                    read_bytes,
                    f"{marker}-{fingerprint}",
                    100,
                    estimated,
                )
                for i, (fingerprint, estimated, read_bytes, status, initial) in enumerate(rows)
            ],
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
        assert {row[0]: row[1:] for row in response.results if row[0].startswith(marker)} == {
            f"{marker}-rows-only": (1, 2.0, 2.0, None, None),
            f"{marker}-mixed": (4, 2.0, 2.0, 4.0, 4.0),
        }
