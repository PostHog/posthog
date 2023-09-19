from posthog.hogql import ast
from posthog.hogql_queries.persons_query_runner import PersonsQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import PersonsQuery, PersonPropertyFilter, HogQLPropertyFilter, PropertyOperator
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events


class TestPersonsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_random_persons(self) -> str:
        random_uuid = str(UUIDT())
        for index in range(10):
            _create_person(
                properties={
                    "email": f"tim{index}@posthog.com",
                    "name": "The Tim",
                    "random_uuid": random_uuid,
                    "index": index,
                },
                team=self.team,
                distinct_ids=[f"id-{index}"],
                is_identified=True,
            )
        flush_persons_and_events()
        return random_uuid

    def _create_runner(self, query: PersonsQuery) -> PersonsQueryRunner:
        return PersonsQueryRunner(team=self.team, query=query)

    def test_basic_persons_query(self):
        self._create_random_persons()
        runner = self._create_runner(PersonsQuery())

        query = runner.to_query()
        self.assertEqual(
            query,
            ast.SelectQuery(
                select=[],
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=ast.Constant(value=True),
                limit=ast.Constant(value=101),
                offset=ast.Constant(value=0),
            ),
        )
        response = runner.run()
        self.assertEqual(len(response.results), 10)

    def test_persons_query_properties(self):
        random_uuid = self._create_random_persons()
        runner = self._create_runner(
            PersonsQuery(
                properties=[
                    PersonPropertyFilter(key="random_uuid", value=random_uuid, operator=PropertyOperator.exact),
                    HogQLPropertyFilter(key="toInt(properties.index) > 5"),
                ]
            )
        )
        self.assertEqual(len(runner.run().results), 4)

    def test_persons_query_fixed_properties(self):
        random_uuid = self._create_random_persons()
        runner = self._create_runner(
            PersonsQuery(
                fixedProperties=[
                    PersonPropertyFilter(key="random_uuid", value=random_uuid, operator=PropertyOperator.exact),
                    HogQLPropertyFilter(key="toInt(properties.index) < 2"),
                ]
            )
        )
        self.assertEqual(len(runner.run().results), 2)

    def test_persons_query_search(self):
        self._create_random_persons()
        runner = self._create_runner(PersonsQuery(search="tim4"))
        self.assertEqual(len(runner.run().results), 1)
