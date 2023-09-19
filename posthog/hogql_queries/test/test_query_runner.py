from typing import Any, List, Literal, Optional, Type
from pydantic import BaseModel
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.team.team import Team
from posthog.test.base import BaseTest
from posthog.types import InsightQueryNode


class TestQuery(BaseModel):
    kind: Literal["TestQuery"] = "TestQuery"
    some_attr: str
    other_attr: Optional[List[Any]] = []


class QueryRunnerTest(BaseTest):
    def setup_test_query_runner_class(self, query_class: Type[InsightQueryNode] = TestQuery):  # type: ignore
        """Setup required methods and attributes of the abstract base class."""

        class TestQueryRunner(QueryRunner):
            query_type = query_class

        TestQueryRunner.__abstractmethods__ = frozenset()

        return TestQueryRunner

    def test_init_with_query_instance(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query=TestQuery(some_attr="bla"), team=self.team)  # type: ignore

        self.assertEqual(runner.query, TestQuery(some_attr="bla"))

    def test_init_with_query_dict(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)  # type: ignore

        self.assertEqual(runner.query, TestQuery(some_attr="bla"))

    def test_serializes_to_json(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)  # type: ignore

        json = runner.toJSON()
        self.assertEqual(json, '{"some_attr":"bla"}')

    def test_serializes_to_json_ignores_empty_dict(self):
        # The below behaviour is not currently implemented, since we're auto-
        # generating the pydantic models for queries, which doesn't allow us
        # setting a custom default value for list and dict type properties.
        #
        # :KLUDGE: In order to receive a stable JSON representation for cache
        # keys we want to ignore semantically equal attributes. E.g. an empty
        # list and None should be treated equally.
        #
        # To achieve this behaviour we ignore None and the default value, which
        # we set to an empty list. It would be even better, if we would
        # implement custom validators for this.
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla", "other_attr": []}, team=self.team)  # type: ignore

        json = runner.toJSON()
        self.assertEqual(json, '{"some_attr":"bla"}')

    def test_cache_key(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)  # type: ignore

        cache_key = runner._cache_key()
        self.assertEqual(cache_key, "cache_f0f2ce8b1f3d107b9671a178b25be2aa")

    def test_cache_key_different_timezone(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)
        team.timezone = "Europe/Vienna"
        team.save()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)  # type: ignore

        cache_key = runner._cache_key()
        self.assertEqual(cache_key, "cache_0fa2172980705adb41741351f40189b7")
