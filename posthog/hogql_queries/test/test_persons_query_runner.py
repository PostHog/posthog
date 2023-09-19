from posthog.hogql import ast
from posthog.hogql_queries.persons_query_runner import PersonsQueryRunner
from posthog.models.utils import UUIDT
from posthog.schema import PersonsQuery
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events


class TestPersonsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_random_persons(self) -> str:
        random_uuid = str(UUIDT())
        for index in range(10):
            _create_person(
                properties={"sneaky_mail": f"tim{index}@posthog.com", "random_uuid": random_uuid, "index": index},
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
                where=None,
                limit=ast.Constant(value=101),
                offset=ast.Constant(value=0),
            ),
        )

        response = runner.run()
        self.assertEqual(len(response.results), 10)
