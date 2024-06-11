import pytest

from posthog.hogql import ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import (
    ActorsQuery,
    PersonPropertyFilter,
    HogQLPropertyFilter,
    PropertyOperator,
    HogQLQuery,
    LifecycleQuery,
    InsightDateRange,
    EventsNode,
    IntervalType,
    InsightActorsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    _create_event,
)
from freezegun import freeze_time
from django.test import override_settings


class TestActorsQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

    def _create_runner(self, query: ActorsQuery) -> ActorsQueryRunner:
        return ActorsQueryRunner(team=self.team, query=query)

    def setUp(self):
        super().setUp()

    def test_default_persons_query(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery())

        query = runner.to_query()
        query = clear_locations(query)
        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["id"]),
                ast.Field(chain=["id"]),
                ast.Field(chain=["created_at"]),
                ast.Constant(value=1),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=None,
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
        )
        assert clear_locations(query) == expected
        response = runner.calculate()
        assert len(response.results) == 10

        assert set(response.results[0][0].keys()) == {"id", "created_at", "distinct_ids", "properties", "is_identified"}
        assert response.results[0][0].get("properties").get("random_uuid") == self.random_uuid
        assert len(response.results[0][0].get("distinct_ids")) > 0

    def test_persons_query_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(
                properties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) > 5"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 4)

    def test_persons_query_fixed_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(
                fixedProperties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) < 2"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 2)

    def test_persons_query_search_email(self):
        self.random_uuid = self._create_random_persons()
        self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"jacob4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(ActorsQuery(search=f"JACOB4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)

    def test_persons_query_search_name(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"Mr Jacob {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)
        runner = self._create_runner(ActorsQuery(search=f"MR JACOB {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)

    def test_persons_query_search_distinct_id(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(ActorsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_persons_query_search_snapshot(self):
        runner = self._create_runner(ActorsQuery(search="SEARCHSTRING"))
        assert pretty_print_in_tests(runner.to_hogql(), self.team.pk) == self.snapshot

    def test_persons_query_aggregation_select_having(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.name", "count()"]))
        results = runner.calculate().results
        self.assertEqual(results, [[f"Mr Jacob {self.random_uuid}", 10]])

    def test_persons_query_order_by(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email"], orderBy=["properties.email DESC"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob9@{self.random_uuid}.posthog.com"])

    def test_persons_query_order_by_with_aliases(self):
        # We use the first column by default as an order key. It used to cause "error redefining alias" errors.
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email as email"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob0@{self.random_uuid}.posthog.com"])

    def test_persons_query_limit(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            ActorsQuery(select=["properties.email"], orderBy=["properties.email DESC"], limit=1)
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob9@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

        runner = self._create_runner(
            ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                limit=1,
                offset=2,
            )
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob7@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_source_hogql_query_poe_on(self):
        self.random_uuid = self._create_random_persons()
        source_query = HogQLQuery(query="SELECT distinct person_id FROM events WHERE event='clicky-4'")
        query = ActorsQuery(
            select=["properties.email"],
            orderBy=["properties.email DESC"],
            source=source_query,
        )
        runner = self._create_runner(query)
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_source_hogql_query_poe_off(self):
        self.random_uuid = self._create_random_persons()
        source_query = HogQLQuery(query="SELECT distinct person_id FROM events WHERE event='clicky-4'")
        query = ActorsQuery(
            select=["properties.email"],
            orderBy=["properties.email DESC"],
            source=source_query,
        )
        runner = self._create_runner(query)
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    def test_source_lifecycle_query(self):
        with freeze_time("2021-01-01T12:00:00Z"):
            self.random_uuid = self._create_random_persons()
        with freeze_time("2021-01-03T12:00:00Z"):
            source_query = LifecycleQuery(
                series=[EventsNode(event="clicky-4")],
                properties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.EXACT,
                    )
                ],
                interval=IntervalType.DAY,
                dateRange=InsightDateRange(date_from="-7d"),
            )
            query = ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                source=InsightActorsQuery(source=source_query),
            )
            runner = self._create_runner(query)
            response = runner.calculate()
            self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])

    def test_persons_query_grouping(self):
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={
                "email": f"jacob0@{random_uuid}.posthog.com",
                "name": f"Mr Jacob {random_uuid}",
                "random_uuid": random_uuid,
                "index": 0,
            },
            team=self.team,
            distinct_ids=[f"id-{random_uuid}-0", f"id-{random_uuid}-1"],
            is_identified=True,
        )
        _create_event(
            distinct_id=f"id-{random_uuid}-0",
            event=f"clicky-0",
            team=self.team,
        )
        _create_event(
            distinct_id=f"id-{random_uuid}-1",
            event=f"clicky-9",
            team=self.team,
        )
        flush_persons_and_events()
        runner = self._create_runner(ActorsQuery(search="posthog.com"))

        response = runner.calculate()
        # Should show a single person despite multiple distinct_ids
        self.assertEqual(len(response.results), 1)
