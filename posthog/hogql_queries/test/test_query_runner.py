from typing import Any, List, Optional, Type
from pydantic import BaseModel
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.test.base import BaseTest


class TestQuery(BaseModel):
    some_attr: str
    other_attr: Optional[List[Any]] = None


class QueryRunnerTest(BaseTest):
    def setup_test_query_runner_class(self, query_class: Type[BaseModel] = TestQuery):
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
        # :KLUDGE: In order to receive a stable JSON representation for cache
        # keys we want to ignore semantically equal attributes. E.g. an empty
        # list and None should be treated equally.
        #
        # To achieve this behaviour we ignore None and the default value, which
        # we set to an empty list.
        #
        # It would be better to write custom validators for this, but we're
        # auto-generating the pydantic models for queries, so we can't do that
        # at the moment.
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla", "other_attr": []}, team=self.team)  # type: ignore

        json = runner.toJSON()
        self.assertEqual(json, '{"some_attr":"bla"}')

    def test_cache_key(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla", "other_attr": []}, team=self.team)  # type: ignore

        cache_key = runner.cache_key()
        self.assertEqual(cache_key, "abc")
