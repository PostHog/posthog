from datetime import datetime, timedelta
from typing import Any, List, Literal, Optional
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from freezegun import freeze_time
from pydantic import BaseModel

from posthog.hogql_queries.query_runner import (
    QueryResponse,
    QueryRunner,
)
from posthog.models.team.team import Team
from posthog.schema import HogQLQueryModifiers, MaterializationMode, HogQLQuery
from posthog.test.base import BaseTest


class TestQuery(BaseModel):
    kind: Literal["TestQuery"] = "TestQuery"
    some_attr: str
    other_attr: Optional[List[Any]] = []


class TestQueryRunner(BaseTest):
    def setup_test_query_runner_class(self):
        """Setup required methods and attributes of the abstract base class."""

        class TestQueryRunner(QueryRunner):
            query_type: TestQuery = TestQuery  # type: ignore[assignment]

            def calculate(self) -> QueryResponse:
                return QueryResponse(results=list())

            def _refresh_frequency(self) -> timedelta:
                return timedelta(minutes=4)

            def _is_stale(self, cached_result_package) -> bool:
                return isoparse(cached_result_package.last_refresh) + timedelta(minutes=10) <= datetime.now(
                    tz=ZoneInfo("UTC")
                )

        TestQueryRunner.__abstractmethods__ = frozenset()

        return TestQueryRunner

    def test_init_with_query_instance(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query=TestQuery(some_attr="bla"), team=self.team)

        self.assertEqual(runner.query, TestQuery(some_attr="bla"))

    def test_init_with_query_dict(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        self.assertEqual(runner.query, TestQuery(some_attr="bla"))

    def test_serializes_to_json(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

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

        runner = TestQueryRunner(query={"some_attr": "bla", "other_attr": []}, team=self.team)

        json = runner.toJSON()
        self.assertEqual(json, '{"some_attr":"bla"}')

    def test_cache_key(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner._cache_key()
        self.assertEqual(cache_key, "cache_b6f14c97c218e0b9c9a8258f7460fd5b")

    def test_cache_key_runner_subclass(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        class TestSubclassQueryRunner(TestQueryRunner):
            pass

        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestSubclassQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner._cache_key()
        self.assertEqual(cache_key, "cache_ec1c2f9715cf9c424b1284b94b1205e6")

    def test_cache_key_different_timezone(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)
        team.timezone = "Europe/Vienna"
        team.save()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner._cache_key()
        self.assertEqual(cache_key, "cache_a6614c0fb564f9c98b1d7b830928c7a1")

    def test_cache_response(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with freeze_time(datetime(2023, 2, 4, 13, 37, 42)):
            # returns fresh response if uncached
            response = runner.run(refresh_requested=False)
            self.assertEqual(response.is_cached, False)
            self.assertEqual(response.last_refresh, "2023-02-04T13:37:42Z")
            self.assertEqual(response.next_allowed_client_refresh, "2023-02-04T13:41:42Z")

            # returns cached response afterwards
            response = runner.run(refresh_requested=False)
            self.assertEqual(response.is_cached, True)

            # return fresh response if refresh requested
            response = runner.run(refresh_requested=True)
            self.assertEqual(response.is_cached, False)

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11, 42)):
            # returns fresh response if stale
            response = runner.run(refresh_requested=False)
            self.assertEqual(response.is_cached, False)

    def test_modifier_passthrough(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
            from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

            materialize("events", "$browser")
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return

        runner = HogQLQueryRunner(
            query=HogQLQuery(query="select properties.$browser from events"),
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.legacy_null_as_string),
        )
        assert "events.`mat_$browser" in runner.calculate().clickhouse

        runner = HogQLQueryRunner(
            query=HogQLQuery(query="select properties.$browser from events"),
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.disabled),
        )
        assert "events.`mat_$browser" not in runner.calculate().clickhouse
