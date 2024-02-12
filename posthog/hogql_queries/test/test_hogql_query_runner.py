from posthog.hogql import ast
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import HogQLPropertyFilter, HogQLQuery, HogQLFilters
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    _create_event,
)


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
