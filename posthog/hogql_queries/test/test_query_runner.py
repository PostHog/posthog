from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from freezegun import freeze_time
from pydantic import BaseModel

from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team, WeekStartDay
from posthog.hogql.constants import LimitContext
from posthog.schema import (
    CacheMissResponse,
    HogQLQuery,
    HogQLQueryModifiers,
    InCohortVia,
    MaterializationMode,
    BounceRatePageViewMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    SessionsV2JoinMode,
    SessionTableVersion,
    RevenueAnalyticsPersonsJoinModeModifier,
    TestBasicQueryResponse,
    TestCachedBasicQueryResponse,
    IntervalType,
)
from posthog.test.base import BaseTest


class TestQuery(BaseModel):
    kind: Literal["TestQuery"] = "TestQuery"
    some_attr: str
    other_attr: Optional[list[Any]] = []


class TestQueryRunner(BaseTest):
    maxDiff = None

    def tearDown(self):
        super().tearDown()
        cache.clear()

    def setup_test_query_runner_class(self):
        """Setup required methods and attributes of the abstract base class."""

        class TestQueryRunner(QueryRunner):
            query: TestQuery
            response: TestBasicQueryResponse
            cached_response: TestCachedBasicQueryResponse

            def calculate(self):
                return TestBasicQueryResponse(
                    results=[
                        ["row", 1, 2, 3],
                        (i for i in range(10)),  # Test support of cache.set with iterators
                    ]
                )

            def _refresh_frequency(self) -> timedelta:
                return timedelta(minutes=4)

            def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False, *args, **kwargs) -> bool:
                if not last_refresh:
                    raise ValueError("Cached results require a last_refresh")

                if lazy:
                    return last_refresh + timedelta(days=1) <= datetime.now(tz=ZoneInfo("UTC"))
                return last_refresh + timedelta(minutes=10) <= datetime.now(tz=ZoneInfo("UTC"))

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

    def test_cache_payload(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestQueryRunner(query={"some_attr": "bla", "tags": {"scene": "foo", "productKey": "bar"}}, team=team)
        cache_payload = runner.get_cache_payload()

        # changes to the cache payload have a significant impact, as they'll
        # result in new cache keys, which effectively invalidates our cache.
        # this causes increased load on the cluster and increased cache
        # memory usage (until old cache items are evicted).
        assert cache_payload == {
            "hogql_modifiers": {
                "bounceRatePageViewMode": BounceRatePageViewMode.COUNT_PAGEVIEWS,
                "convertToProjectTimezone": True,
                "inCohortVia": InCohortVia.AUTO,
                "materializationMode": MaterializationMode.LEGACY_NULL_AS_NULL,
                "optimizeJoinedFilters": False,
                "personsArgMaxVersion": PersonsArgMaxVersion.AUTO,
                "personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                "revenueAnalyticsPersonsJoinMode": RevenueAnalyticsPersonsJoinModeModifier.ID,
                "sessionTableVersion": SessionTableVersion.AUTO,
                "sessionsV2JoinMode": SessionsV2JoinMode.STRING,
                "useMaterializedViews": True,
                "usePresortedEventsTable": False,
            },
            "limit_context": LimitContext.QUERY,
            "query": {"kind": "TestQuery", "some_attr": "bla"},
            "query_runner": "TestQueryRunner",
            "team_id": 42,
            "timezone": "UTC",
            "week_start_day": WeekStartDay.SUNDAY,
            "version": 2,
        }

    def test_cache_payload_week_interval(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization, week_start_day=WeekStartDay.MONDAY)
        runner = TestQueryRunner(query={"some_attr": "bla", "tags": {"scene": "foo", "productKey": "bar"}}, team=team)
        runner.query_date_range = QueryDateRange(
            team=team, date_range=None, interval=IntervalType.WEEK, now=datetime.now()
        )

        cache_payload = runner.get_cache_payload()
        assert cache_payload["week_start_day"] == WeekStartDay.MONDAY

    def test_cache_key(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_67429a7b0c61b8501e8a94ce1ff98263"

    def test_cache_key_runner_subclass(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        class TestSubclassQueryRunner(TestQueryRunner):
            pass

        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestSubclassQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_b1f3e920d3349bb9cd9debe535b38e61"

    def test_cache_key_different_timezone(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)
        team.timezone = "Europe/Vienna"
        team.save()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_4c137679d6e1f4c56dbe8fafd11ed075"

    @mock.patch("django.db.transaction.on_commit")
    def test_cache_response(self, mock_on_commit):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with freeze_time(datetime(2023, 2, 4, 13, 37, 42)):
            # in cache-only mode, returns cache miss response if uncached
            response = runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
            self.assertIsInstance(response, CacheMissResponse)

            # returns fresh response if uncached
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            self.assertEqual(response.next_allowed_client_refresh.isoformat(), "2023-02-04T13:41:42+00:00")

            # returns cached response afterwards
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)

            # return fresh response if refresh requested
            response = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11, 42)):
            # returns fresh response if stale
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            mock_on_commit.assert_not_called()

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11 + 5, 42)):
            # returns cached response - does not kick off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_not_called()

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11 + 11, 42)):
            # returns cached response but kicks off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_called_once()

        with freeze_time(datetime(2023, 2, 4, 23, 55, 42)):
            # returns cached response for extended time
            response = runner.run(execution_mode=ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_called_once()  # still once

        mock_on_commit.reset_mock()
        with freeze_time(datetime(2023, 2, 5, 23, 55, 42)):
            # returns cached response for extended time but finally kicks off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_called_once()

    @mock.patch("django.db.transaction.on_commit")
    def test_recent_cache_calculate_async_if_stale_and_blocking_on_miss(self, mock_on_commit):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with freeze_time(datetime(2023, 2, 4, 13, 37, 42)):
            # in cache-only mode, returns cache miss response if uncached
            response = runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
            self.assertIsInstance(response, CacheMissResponse)

            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            self.assertEqual(response.next_allowed_client_refresh.isoformat(), "2023-02-04T13:41:42+00:00")

            # returns cached response afterwards
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11, 42)):
            # returns fresh response if stale
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )
            self.assertIsInstance(response, TestCachedBasicQueryResponse)
            # Should kick off the calculation in the background
            self.assertEqual(response.is_cached, True)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            mock_on_commit.assert_called_once()

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
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING),
        )
        response = runner.calculate()
        assert response.clickhouse is not None
        assert "events.`mat_$browser" in response.clickhouse

        runner = HogQLQueryRunner(
            query=HogQLQuery(query="select properties.$browser from events"),
            team=self.team,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
        )
        response = runner.calculate()
        assert response.clickhouse is not None
        assert "events.`mat_$browser" not in response.clickhouse
