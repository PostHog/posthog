from datetime import UTC, datetime
from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    CachedHogQLQueryResponse,
    HogQLFilters,
    HogQLPropertyFilter,
    HogQLQuery,
    HogQLQueryResponse,
    HogQLVariable,
)

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.user_query_validator import HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG, OFFSET_NOT_ALLOWED_MESSAGE
from posthog.hogql.visitor import clear_locations

from posthog.caching.utils import ThresholdMode, staleness_threshold_map
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.insight_variable import InsightVariable
from posthog.models.utils import UUIDT

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestHogQLQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    random_uuid: str

    def _create_random_persons(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        for index in range(10):
            _create_person(
                properties={
                    "email": f"jacob{index}@{random_uuid}.posthog.com",
                    "name": f"Mr Jacob {random_uuid}",
                    "random_uuid": random_uuid,
                    "index": index,
                },
                team=self.team,
                distinct_ids=[f"id-{random_uuid}-{index}"],
                is_identified=True,
            )
            _create_event(
                distinct_id=f"id-{random_uuid}-{index}",
                event=f"clicky-{index}",
                team=self.team,
            )
        flush_persons_and_events()
        return random_uuid

    def _create_runner(self, query: HogQLQuery) -> HogQLQueryRunner:
        return HogQLQueryRunner(team=self.team, query=query)

    def setUp(self):
        super().setUp()
        self.random_uuid = self._create_random_persons()

    def test_default_hogql_query(self):
        runner = self._create_runner(HogQLQuery(query="select count(event) from events"))
        query = runner.to_query()
        query = clear_locations(query)
        expected = ast.SelectQuery(
            select=[ast.Call(name="count", args=[ast.Field(chain=["event"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        )
        self.assertEqual(clear_locations(query), expected)
        response = runner.calculate()
        self.assertEqual(response.results[0][0], 10)

        self.assertEqual(response.hasMore, False)
        self.assertIsNotNone(response.limit)

    def test_default_hogql_query_with_limit(self):
        runner = self._create_runner(HogQLQuery(query="select event from events limit 5"))
        response = runner.calculate()
        assert response.results is not None
        self.assertEqual(len(response.results), 5)
        self.assertNotIn("hasMore", response)

    def test_hogql_query_filters(self):
        runner = self._create_runner(
            HogQLQuery(
                query="select count(event) from events where {filters}",
                filters=HogQLFilters(properties=[HogQLPropertyFilter(key="event='clicky-3'")]),
            )
        )
        query = runner.to_query()
        query = clear_locations(query)
        expected = ast.SelectQuery(
            select=[ast.Call(name="count", args=[ast.Field(chain=["event"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="clicky-3"),
            ),
        )
        self.assertEqual(clear_locations(query), expected)
        response = runner.calculate()
        self.assertEqual(response.results[0][0], 1)

    def test_hogql_query_values(self):
        runner = self._create_runner(
            HogQLQuery(
                query="select count(event) from events where event={e}",
                values={"e": "clicky-3"},
            )
        )
        query = runner.to_query()
        query = clear_locations(query)
        expected = ast.SelectQuery(
            select=[ast.Call(name="count", args=[ast.Field(chain=["event"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="clicky-3"),
            ),
        )
        self.assertEqual(clear_locations(query), expected)
        response = runner.calculate()
        self.assertEqual(response.results[0][0], 1)

    def test_cache_target_age_is_two_hours_in_future_after_run(self):
        runner = self._create_runner(HogQLQuery(query="select count(event) from events"))

        fixed_now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
        expected_target_age = fixed_now + staleness_threshold_map[ThresholdMode.DEFAULT]["day"]

        with patch("posthog.hogql_queries.query_runner.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            mock_datetime.timezone.utc = UTC

            response = cast(CachedHogQLQueryResponse, runner.run())

            self.assertIsNotNone(response.cache_target_age)
            self.assertEqual(response.cache_target_age, expected_target_age)

    def test_variables_in_hog_expression(self):
        variable = InsightVariable.objects.create(team=self.team, name="Foo", code_name="foo", type="Boolean")
        variable_id = str(variable.id)

        runner = self._create_runner(
            HogQLQuery(
                query="select {variables.foo ? 'exists' : 'does not'}",
                variables={
                    variable_id: HogQLVariable(code_name=variable.code_name, variableId=variable_id, value=True)
                },
            )
        )

        response = runner.calculate()
        self.assertEqual(response.results[0][0], "exists")

    def test_variables_in_hog_expression_sql(self):
        variable = InsightVariable.objects.create(team=self.team, name="Bar", code_name="bar", type="Boolean")
        variable_id = str(variable.id)

        _create_event(distinct_id=f"id-{self.random_uuid}-3", event="clicky-3", team=self.team)
        flush_persons_and_events()

        query = "select count() from events where {variables.bar ? sql(event = 'clicky-3') : sql(event = 'clicky-4')}"

        runner_true = self._create_runner(
            HogQLQuery(
                query=query,
                variables={
                    variable_id: HogQLVariable(code_name=variable.code_name, variableId=variable_id, value=True)
                },
            )
        )
        result_true = runner_true.calculate()
        self.assertEqual(result_true.results[0][0], 2)

        runner_false = self._create_runner(
            HogQLQuery(
                query=query,
                variables={
                    variable_id: HogQLVariable(code_name=variable.code_name, variableId=variable_id, value=False)
                },
            )
        )
        result_false = runner_false.calculate()
        self.assertEqual(result_false.results[0][0], 1)

    def test_invalid_connection_id_raises_exposed_hogql_error(self):
        runner = self._create_runner(
            HogQLQuery(
                query="select 1",
                connectionId=str(UUIDT()),
            )
        )

        with self.assertRaises(ExposedHogQLError):
            runner.calculate()

    @patch("posthog.hogql_queries.hogql_query_runner.execute_hogql_query")
    def test_send_raw_query_uses_raw_query_string_for_direct_connections(self, mock_execute_hogql_query):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        mock_execute_hogql_query.return_value = HogQLQueryResponse(results=[(1,)], columns=["value"], types=[])

        runner = self._create_runner(
            HogQLQuery(
                query="select 1::int as value",
                connectionId=str(source.id),
                sendRawQuery=True,
            )
        )

        response = runner.calculate()

        self.assertEqual(response.results, [(1,)])
        mock_execute_hogql_query.assert_called_once()
        self.assertEqual(mock_execute_hogql_query.call_args.kwargs["query"], "select 1::int as value")
        self.assertEqual(mock_execute_hogql_query.call_args.kwargs["connection_id"], str(source.id))
        self.assertEqual(mock_execute_hogql_query.call_args.kwargs["send_raw_query"], True)

    @patch("posthog.hogql_queries.hogql_query_runner.execute_hogql_query")
    def test_send_raw_query_is_ignored_without_direct_connection(self, mock_execute_hogql_query):
        mock_execute_hogql_query.return_value = HogQLQueryResponse(results=[(10,)], columns=["count"], types=[])

        runner = self._create_runner(
            HogQLQuery(
                query="select count(event) from events limit 100",
                sendRawQuery=True,
            )
        )

        response = runner.calculate()

        self.assertEqual(response.results, [(10,)])
        mock_execute_hogql_query.assert_called_once()
        self.assertIsInstance(mock_execute_hogql_query.call_args.kwargs["query"], ast.SelectQuery)
        self.assertNotIn("send_raw_query", mock_execute_hogql_query.call_args.kwargs)

    def test_soft_deleted_connection_id_raises_exposed_hogql_error(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            deleted=True,
        )
        runner = self._create_runner(
            HogQLQuery(
                query="select 1",
                connectionId=str(source.id),
            )
        )

        with self.assertRaises(ExposedHogQLError):
            runner.calculate()

    def test_non_direct_connection_id_raises_exposed_hogql_error(self):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        )

        runner = self._create_runner(
            HogQLQuery(
                query="select * from stripe.customers limit 1",
                connectionId=str(source.id),
            )
        )

        with self.assertRaises(ExposedHogQLError):
            runner.calculate()

    @parameterized.expand(
        [
            # Plain OFFSET on SelectQuery
            ("top_level", "select event from events limit 10 offset 5"),
            # Recursion into a subquery
            ("subquery", "select * from (select event from events limit 10 offset 5) sub"),
            # Distinct AST node: SelectSetQuery.offset (OFFSET at UNION level)
            (
                "select_set_outer",
                "(select event from events limit 5) union all (select event from events limit 5) limit 10 offset 5",
            ),
            # Distinct AST node: LimitByExpr.offset_value
            ("limit_by", "select event, timestamp from events limit 5 by event offset 10"),
            # OFFSET arrives via placeholder — proves hook runs after to_query() substitution.
            ("placeholder", "select event from events limit 10 offset {o}"),
        ]
    )
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_query_service_rejects_offset(self, _name, sql, _mock_flag):
        values = {"o": 50} if "{o}" in sql else None
        runner = self._create_runner(HogQLQuery(query=sql, values=values))
        runner.is_query_service = True

        with self.assertRaises(QueryError) as ctx:
            runner.calculate()
        self.assertEqual(OFFSET_NOT_ALLOWED_MESSAGE, str(ctx.exception))

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_query_service_allows_offset_when_org_on_allow_list(self, _mock_flag):
        # Grandfathered via the allow-list flag → query passes through to execution.
        runner = self._create_runner(HogQLQuery(query="select event from events limit 10 offset 5"))
        runner.is_query_service = True

        response = runner.calculate()
        self.assertEqual(len(response.results), 5)

    def test_query_service_fails_open_when_flag_service_errors(self):
        # Flag-service outage must not cascade into rejecting previously-valid traffic.
        # Scope the error to our flag only — a blanket raise would break unrelated flag checks
        # downstream in the query execution path.
        def flag_side_effect(flag, *_args, **_kwargs):
            if flag == HOGQL_PERSONAL_API_KEY_OFFSET_ALLOWED_FLAG:
                raise RuntimeError("flag service down")
            return False

        runner = self._create_runner(HogQLQuery(query="select event from events limit 10 offset 5"))
        runner.is_query_service = True

        with patch("posthoganalytics.feature_enabled", side_effect=flag_side_effect):
            response = runner.calculate()
        self.assertEqual(len(response.results), 5)

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_non_query_service_allows_offset(self, _mock_flag):
        # Product queries (Trends/Funnels/etc.) have is_query_service=False — must pass through
        # even when the flag says "deny everything." Guards the `if self.is_query_service:` gate.
        runner = self._create_runner(HogQLQuery(query="select event from events limit 10 offset 5"))

        response = runner.calculate()
        self.assertEqual(len(response.results), 5)
