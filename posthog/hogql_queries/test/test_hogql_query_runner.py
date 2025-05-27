from typing import cast

from posthog.caching.utils import staleness_threshold_map, ThresholdMode
from posthog.hogql import ast
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import HogQLASTQuery, HogQLPropertyFilter, HogQLQuery, HogQLFilters, CachedHogQLQueryResponse
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    _create_event,
)
from datetime import datetime, UTC
from unittest.mock import patch


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

    def _create_runner(self, query: HogQLQuery | HogQLASTQuery) -> HogQLQueryRunner:
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

    def test_default_hogql_query_ast(self):
        query_input = {
            "__hx_ast": "SelectQuery",
            "select": [{"__hx_ast": "Call", "name": "count", "args": [{"__hx_ast": "Field", "chain": ["event"]}]}],
            "select_from": {"__hx_ast": "JoinExpr", "table": {"__hx_ast": "Field", "chain": ["events"]}},
        }
        runner = self._create_runner(HogQLASTQuery(query=query_input))
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
