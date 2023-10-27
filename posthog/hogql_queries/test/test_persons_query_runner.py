from posthog.hogql import ast
from posthog.hogql.visitor import clear_locations
from posthog.hogql_queries.persons_query_runner import PersonsQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import (
    PersonsQuery,
    PersonPropertyFilter,
    HogQLPropertyFilter,
    PropertyOperator,
    HogQLQuery,
    LifecycleQuery,
    DateRange,
    EventsNode,
    IntervalType,
    InsightPersonsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    _create_event,
)
from freezegun import freeze_time


class TestPersonsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    random_uuid: str

    def _create_random_persons(self) -> str:
        random_uuid = str(UUIDT())
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

    def _create_runner(self, query: PersonsQuery) -> PersonsQueryRunner:
        return PersonsQueryRunner(team=self.team, query=query)

    def setUp(self):
        super().setUp()

    def test_default_persons_query(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery())

        query = runner.to_query()
        query = clear_locations(query)
        expected = ast.SelectQuery(
            select=[
                ast.Tuple(
                    exprs=[
                        ast.Field(chain=["id"]),
                        ast.Field(chain=["properties"]),
                        ast.Field(chain=["created_at"]),
                        ast.Field(chain=["is_identified"]),
                    ]
                ),
                ast.Field(chain=["id"]),
                ast.Field(chain=["created_at"]),
                ast.Constant(value=1),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=None,
            limit=ast.Constant(value=101),
            offset=ast.Constant(value=0),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
        )
        self.assertEqual(clear_locations(query), expected)
        response = runner.calculate()
        self.assertEqual(len(response.results), 10)

    def test_persons_query_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            PersonsQuery(
                properties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.exact,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) > 5"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 4)

    def test_persons_query_fixed_properties(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            PersonsQuery(
                fixedProperties=[
                    PersonPropertyFilter(
                        key="random_uuid",
                        value=self.random_uuid,
                        operator=PropertyOperator.exact,
                    ),
                    HogQLPropertyFilter(key="toInt(properties.index) < 2"),
                ]
            )
        )
        self.assertEqual(len(runner.calculate().results), 2)

    def test_persons_query_search_email(self):
        self.random_uuid = self._create_random_persons()
        self._create_random_persons()
        runner = self._create_runner(PersonsQuery(search=f"jacob4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(PersonsQuery(search=f"JACOB4@{self.random_uuid}.posthog"))
        self.assertEqual(len(runner.calculate().results), 1)

    def test_persons_query_search_name(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery(search=f"Mr Jacob {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)
        runner = self._create_runner(PersonsQuery(search=f"MR JACOB {self.random_uuid}"))
        self.assertEqual(len(runner.calculate().results), 10)

    def test_persons_query_search_distinct_id(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)
        runner = self._create_runner(PersonsQuery(search=f"id-{self.random_uuid}-9"))
        self.assertEqual(len(runner.calculate().results), 1)

    def test_persons_query_aggregation_select_having(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery(select=["properties.name", "count()"]))
        results = runner.calculate().results
        self.assertEqual(results, [[f"Mr Jacob {self.random_uuid}", 10]])

    def test_persons_query_order_by(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery(select=["properties.email"], orderBy=["properties.email DESC"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob9@{self.random_uuid}.posthog.com"])

    def test_persons_query_order_by_with_aliases(self):
        # We use the first column by default as an order key. It used to cause "error redefining alias" errors.
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(PersonsQuery(select=["properties.email as email"]))
        results = runner.calculate().results
        self.assertEqual(results[0], [f"jacob0@{self.random_uuid}.posthog.com"])

    def test_persons_query_limit(self):
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(
            PersonsQuery(select=["properties.email"], orderBy=["properties.email DESC"], limit=1)
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob9@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

        runner = self._create_runner(
            PersonsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                limit=1,
                offset=2,
            )
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob7@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

    def test_source_hogql_query(self):
        self.random_uuid = self._create_random_persons()
        source_query = HogQLQuery(query="SELECT distinct person_id FROM events WHERE event='clicky-4'")
        query = PersonsQuery(
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
                        operator=PropertyOperator.exact,
                    )
                ],
                interval=IntervalType.day,
                dateRange=DateRange(date_from="-7d"),
            )
            query = PersonsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                source=InsightPersonsQuery(source=source_query),
            )
            runner = self._create_runner(query)
            response = runner.calculate()
            self.assertEqual(response.results, [[f"jacob4@{self.random_uuid}.posthog.com"]])
