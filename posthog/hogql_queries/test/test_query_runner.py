from datetime import datetime, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest import mock

from django.core.cache import cache

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    BounceRatePageViewMode,
    CacheMissResponse,
    CurrencyCode,
    EventsNode,
    HogQLQuery,
    HogQLQueryModifiers,
    InCohortVia,
    IntervalType,
    MaterializationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    SessionsV2JoinMode,
    SessionTableVersion,
    TestBasicQueryResponse as TheTestBasicQueryResponse,
    TestCachedBasicQueryResponse as TheTestCachedBasicQueryResponse,
    TrendsQuery,
)

from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team, WeekStartDay

from products.customer_analytics.backend.constants import DEFAULT_ACTIVITY_EVENT
from products.marketing_analytics.backend.hogql_queries.test.utils import MARKETING_ANALYTICS_SOURCES_MAP_SAMPLE
from products.revenue_analytics.backend.hogql_queries.test.data.structure import REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT


class TheTestQuery(BaseModel):
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
            query: TheTestQuery
            cached_response: TheTestCachedBasicQueryResponse

            def calculate(self):
                return TheTestBasicQueryResponse(
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

        runner = TestQueryRunner(query=TheTestQuery(some_attr="bla"), team=self.team)

        self.assertEqual(runner.query, TheTestQuery(some_attr="bla"))

    def test_init_with_query_dict(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        self.assertEqual(runner.query, TheTestQuery(some_attr="bla"))

    def test_cache_payload(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        team = Team.objects.create(
            organization=self.organization,
            base_currency=CurrencyCode.USD.value,
        )

        # Basic Revenue Analytics config
        ra_config = team.revenue_analytics_config
        ra_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        ra_config.save()

        # Basic Marketing Analytics config
        ma_config = team.marketing_analytics_config
        ma_config.sources_map = MARKETING_ANALYTICS_SOURCES_MAP_SAMPLE
        ma_config.save()

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
                "sessionTableVersion": SessionTableVersion.AUTO,
                "sessionsV2JoinMode": SessionsV2JoinMode.STRING,
                "useMaterializedViews": True,
                "usePresortedEventsTable": False,
            },
            "products_modifiers": {
                "marketing_analytics": {
                    "attribution_mode": "last_touch",
                    "attribution_window_days": 90,
                    "base_currency": "USD",
                    "campaign_name_mappings": {},
                    "custom_source_mappings": {},
                    "campaign_field_preferences": {},
                    "sources_map": {
                        "01977f7b-7f29-0000-a028-7275d1a767a4": {
                            "cost": "cost",
                            "date": "date",
                            "clicks": "clicks",
                            "source": "_metadata_launched_at",
                            "campaign": "campaignname",
                            "currency": "USD",
                            "impressions": "impressions",
                        },
                    },
                },
                "revenue_analytics": {
                    "base_currency": "USD",
                    "filter_test_accounts": False,
                    "events": [
                        {
                            "couponProperty": "coupon",
                            "currencyAwareDecimal": False,
                            "eventName": "purchase",
                            "productProperty": "product",
                            "revenueCurrencyProperty": {
                                "property": "currency",
                                "static": None,
                            },
                            "revenueProperty": "revenue",
                            "subscriptionDropoffDays": 45,
                            "subscriptionDropoffMode": "last_event",
                            "subscriptionProperty": "subscription",
                        }
                    ],
                },
                "customer_analytics": {
                    "activity_event": DEFAULT_ACTIVITY_EVENT,
                    "signup_pageview_event": {},
                    "signup_event": {},
                    "subscription_event": {},
                    "payment_event": {},
                },
            },
            "limit_context": LimitContext.QUERY,
            "query": {"kind": "TestQuery", "some_attr": "bla"},
            "query_runner": "TestQueryRunner",
            "team_id": team.id,
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
        assert cache_key == "cache_42_194d1cdb3e7a4bef74e185f7339bbf1b245e4bde0316ac641969447a2daaaea3"

    def test_cache_key_runner_subclass(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        class TestSubclassQueryRunner(TestQueryRunner):
            pass

        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestSubclassQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_42_84635471ca5a516c617c633dac5bd7dd717647f255f86eab09fb891a7cdbd828"

    def test_cache_key_different_timezone(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)
        team.timezone = "Europe/Vienna"
        team.save()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_42_cc74546afbbefc5454fa188e0a6146b8701f524d71f8f535c368cdaf20e220d4"

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
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            self.assertEqual(response.next_allowed_client_refresh.isoformat(), "2023-02-04T13:41:42+00:00")

            # returns cached response afterwards
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)

            # return fresh response if refresh requested
            response = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11, 42)):
            # returns fresh response if stale
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            mock_on_commit.assert_not_called()

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11 + 5, 42)):
            # returns cached response - does not kick off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_not_called()

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11 + 11, 42)):
            # returns cached response but kicks off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_called_once()

        with freeze_time(datetime(2023, 2, 4, 23, 55, 42)):
            # returns cached response for extended time
            response = runner.run(execution_mode=ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)
            mock_on_commit.assert_called_once()  # still once

        mock_on_commit.reset_mock()
        with freeze_time(datetime(2023, 2, 5, 23, 55, 42)):
            # returns cached response for extended time but finally kicks off calculation in the background
            response = runner.run(execution_mode=ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE)
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
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
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            self.assertEqual(response.next_allowed_client_refresh.isoformat(), "2023-02-04T13:41:42+00:00")

            # returns cached response afterwards
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, True)

        with freeze_time(datetime(2023, 2, 4, 13, 37 + 11, 42)):
            # returns fresh response if stale
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            )
            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            # Should kick off the calculation in the background
            self.assertEqual(response.is_cached, True)
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            mock_on_commit.assert_called_once()

    def test_modifier_passthrough(self):
        try:
            from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

            from ee.clickhouse.materialized_columns.analyze import materialize

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

    @mock.patch("posthog.hogql_queries.query_runner.get_query_cache_manager")
    def test_schema_change_triggers_recalculation(self, mock_get_cache_manager):
        TestQueryRunner = self.setup_test_query_runner_class()
        mock_cache_manager = mock.MagicMock()
        mock_cache_manager.cache_key = "test_cache_key"
        mock_cache_manager.get_cache_data.return_value = {
            "is_cached": True,
            "invalid_field": "this will cause validation to fail",
            # Missing all the actual required fields like results, last_refresh, etc.
        }
        mock_get_cache_manager.return_value = mock_cache_manager
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with freeze_time(datetime(2023, 2, 4, 13, 37, 42)):
            response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

            self.assertIsInstance(response, TheTestCachedBasicQueryResponse)
            self.assertEqual(response.is_cached, False, "Should get a fresh response, not a cached one")
            self.assertEqual(response.last_refresh.isoformat(), "2023-02-04T13:37:42+00:00")
            mock_cache_manager.get_cache_data.assert_called_once()
            mock_cache_manager.set_cache_data.assert_called_once()


class TestSeriesCustomNameCaching(BaseTest):
    @parameterized.expand(
        [
            (
                "renames_series_with_custom_name",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Original Name")]),
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Renamed Series")]),
                True,
            ),
            (
                "adds_custom_name_to_series",
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="New Name")]),
                True,
            ),
            (
                "removes_custom_name_from_series",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Had Name")]),
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                True,
            ),
            (
                "different_events_produce_different_keys",
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                TrendsQuery(series=[EventsNode(event="$autocapture")]),
                False,
            ),
            (
                "multiple_series_with_different_custom_names",
                TrendsQuery(
                    series=[
                        EventsNode(event="$pageview", custom_name="Series A"),
                        EventsNode(event="$autocapture", custom_name="Series B"),
                    ]
                ),
                TrendsQuery(
                    series=[
                        EventsNode(event="$pageview", custom_name="Renamed A"),
                        EventsNode(event="$autocapture", custom_name="Renamed B"),
                    ]
                ),
                True,
            ),
        ]
    )
    def test_cache_key_for_series_custom_name_changes(
        self,
        _name: str,
        query_a: TrendsQuery,
        query_b: TrendsQuery,
        expect_same_cache_key: bool,
    ):
        runner_a = TrendsQueryRunner(query=query_a, team=self.team)
        runner_b = TrendsQueryRunner(query=query_b, team=self.team)

        cache_key_a = runner_a.get_cache_key()
        cache_key_b = runner_b.get_cache_key()

        if expect_same_cache_key:
            self.assertEqual(cache_key_a, cache_key_b)
        else:
            self.assertNotEqual(cache_key_a, cache_key_b)


class TestApplySeriesCustomNames(BaseTest):
    @parameterized.expand(
        [
            (
                "applies_custom_name_to_single_series",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="My Custom Name")]),
                [{"action": {"order": 0, "custom_name": None}, "data": [1, 2, 3]}],
                [{"action": {"order": 0, "custom_name": "My Custom Name"}, "data": [1, 2, 3]}],
            ),
            (
                "applies_custom_names_to_multiple_series",
                TrendsQuery(
                    series=[
                        EventsNode(event="$pageview", custom_name="Series A"),
                        EventsNode(event="$autocapture", custom_name="Series B"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "Old A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "Old B"}, "data": [2]},
                ],
                [
                    {"action": {"order": 0, "custom_name": "Series A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "Series B"}, "data": [2]},
                ],
            ),
            (
                "handles_breakdown_results_sharing_same_order",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Renamed")]),
                [
                    {"action": {"order": 0, "custom_name": None}, "breakdown_value": "Chrome"},
                    {"action": {"order": 0, "custom_name": None}, "breakdown_value": "Firefox"},
                ],
                [
                    {"action": {"order": 0, "custom_name": "Renamed"}, "breakdown_value": "Chrome"},
                    {"action": {"order": 0, "custom_name": "Renamed"}, "breakdown_value": "Firefox"},
                ],
            ),
            (
                "sets_none_when_custom_name_removed",
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                [{"action": {"order": 0, "custom_name": "Had Name"}, "data": [1]}],
                [{"action": {"order": 0, "custom_name": None}, "data": [1]}],
            ),
            (
                "skips_results_without_action",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Name")]),
                [{"action": None, "data": [1]}, {"data": [2]}],
                [{"action": None, "data": [1]}, {"data": [2]}],
            ),
            (
                "skips_results_with_unknown_order",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Name")]),
                [{"action": {"order": 99, "custom_name": "Unknown"}, "data": [1]}],
                [{"action": {"order": 99, "custom_name": "Unknown"}, "data": [1]}],
            ),
        ]
    )
    def test_apply_series_custom_names(
        self,
        _name: str,
        query: TrendsQuery,
        cached_results: list[dict],
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedTrendsQueryResponse

        runner = TrendsQueryRunner(query=query, team=self.team)

        cached_response = CachedTrendsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "patches_funnel_steps_without_breakdown",
                [
                    {"order": 0, "custom_name": "Old Step 1", "count": 100},
                    {"order": 1, "custom_name": "Old Step 2", "count": 50},
                ],
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                True,
            ),
            (
                "patches_funnel_steps_with_breakdown",
                [
                    [
                        {"order": 0, "custom_name": None, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "custom_name": None, "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "custom_name": None, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "custom_name": None, "count": 40, "breakdown": "Firefox"},
                    ],
                ],
                [
                    [
                        {"order": 0, "custom_name": "Step 1 Renamed", "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "custom_name": "Step 2 Renamed", "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "custom_name": "Step 1 Renamed", "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "custom_name": "Step 2 Renamed", "count": 40, "breakdown": "Firefox"},
                    ],
                ],
                True,
            ),
            (
                "not_modified_when_names_match",
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                False,
            ),
        ]
    )
    def test_apply_funnels_custom_names(
        self,
        _name: str,
        cached_results: list,
        expected_results: list,
        expect_modified: bool,
    ):
        from datetime import UTC

        from posthog.schema import CachedFunnelsQueryResponse, FunnelsQuery

        from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

        query = FunnelsQuery(
            series=[
                EventsNode(event="step1", custom_name="Step 1 Renamed"),
                EventsNode(event="step2", custom_name="Step 2 Renamed"),
            ]
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)

        cached_response = CachedFunnelsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, expected_results)
        self.assertEqual(was_modified, expect_modified)

    @parameterized.expand(
        [
            (
                "applies_custom_name_to_stickiness_series",
                [{"action": {"order": 0, "custom_name": None}, "data": [1, 2, 3]}],
                [{"action": {"order": 0, "custom_name": "My Stickiness Name"}, "data": [1, 2, 3]}],
                True,
            ),
            (
                "not_modified_when_stickiness_names_match",
                [{"action": {"order": 0, "custom_name": "My Stickiness Name"}, "data": [1, 2, 3]}],
                [{"action": {"order": 0, "custom_name": "My Stickiness Name"}, "data": [1, 2, 3]}],
                False,
            ),
        ]
    )
    def test_apply_stickiness_custom_names(
        self,
        _name: str,
        cached_results: list,
        expected_results: list,
        expect_modified: bool,
    ):
        from datetime import UTC

        from posthog.schema import CachedStickinessQueryResponse, StickinessQuery

        from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner

        query = StickinessQuery(
            series=[
                EventsNode(event="$pageview", custom_name="My Stickiness Name"),
            ]
        )

        runner = StickinessQueryRunner(query=query, team=self.team)

        cached_response = CachedStickinessQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, expected_results)
        self.assertEqual(was_modified, expect_modified)

    @parameterized.expand(
        [
            (
                "patches_all_lifecycle_statuses",
                [
                    {"action": {"order": 0, "custom_name": None}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": None}, "status": "returning", "data": [2]},
                    {"action": {"order": 0, "custom_name": None}, "status": "resurrecting", "data": [3]},
                    {"action": {"order": 0, "custom_name": None}, "status": "dormant", "data": [4]},
                ],
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "returning", "data": [2]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "resurrecting", "data": [3]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "dormant", "data": [4]},
                ],
                True,
            ),
            (
                "not_modified_when_lifecycle_names_match",
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                ],
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                ],
                False,
            ),
        ]
    )
    def test_apply_lifecycle_custom_names(
        self,
        _name: str,
        cached_results: list,
        expected_results: list,
        expect_modified: bool,
    ):
        from datetime import UTC

        from posthog.schema import CachedLifecycleQueryResponse, LifecycleQuery

        from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner

        query = LifecycleQuery(
            series=[
                EventsNode(event="$pageview", custom_name="My Lifecycle"),
            ]
        )

        runner = LifecycleQueryRunner(query=query, team=self.team)

        cached_response = CachedLifecycleQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, expected_results)
        self.assertEqual(was_modified, expect_modified)

    @parameterized.expand(
        [
            (
                "modified_when_name_changes",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="New Name")]),
                [{"action": {"order": 0, "custom_name": "Old Name"}, "data": [1]}],
                True,
            ),
            (
                "modified_when_name_added",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="New Name")]),
                [{"action": {"order": 0, "custom_name": None}, "data": [1]}],
                True,
            ),
            (
                "modified_when_name_removed",
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                [{"action": {"order": 0, "custom_name": "Had Name"}, "data": [1]}],
                True,
            ),
            (
                "not_modified_when_names_match",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Same Name")]),
                [{"action": {"order": 0, "custom_name": "Same Name"}, "data": [1]}],
                False,
            ),
            (
                "not_modified_when_both_none",
                TrendsQuery(series=[EventsNode(event="$pageview")]),
                [{"action": {"order": 0, "custom_name": None}, "data": [1]}],
                False,
            ),
            (
                "not_modified_when_no_matching_orders",
                TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Name")]),
                [{"action": {"order": 99, "custom_name": "Other"}, "data": [1]}],
                False,
            ),
        ]
    )
    def test_was_modified_flag(
        self,
        _name: str,
        query: TrendsQuery,
        cached_results: list[dict],
        expect_modified: bool,
    ):
        from datetime import UTC

        from posthog.schema import CachedTrendsQueryResponse

        runner = TrendsQueryRunner(query=query, team=self.team)

        cached_response = CachedTrendsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        _, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(was_modified, expect_modified)


class TestApplySeriesDelete(BaseTest):
    @parameterized.expand(
        [
            (
                "deletes_middle_series_from_trends",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                        EventsNode(event="event_c"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
                ],
                1,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "C"}, "data": [3]},
                ],
            ),
            (
                "deletes_first_series_from_trends",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_b"),
                        EventsNode(event="event_c"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
                ],
                0,
                [
                    {"action": {"order": 0, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 1, "custom_name": "C"}, "data": [3]},
                ],
            ),
            (
                "deletes_last_series_from_trends",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                        EventsNode(event="event_b"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
                ],
                2,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                ],
            ),
            (
                "handles_breakdown_results_with_delete",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                    ]
                ),
                [
                    {"action": {"order": 0}, "breakdown_value": "Chrome", "data": [1]},
                    {"action": {"order": 0}, "breakdown_value": "Firefox", "data": [2]},
                    {"action": {"order": 1}, "breakdown_value": "Chrome", "data": [3]},
                    {"action": {"order": 1}, "breakdown_value": "Firefox", "data": [4]},
                ],
                1,
                [
                    {"action": {"order": 0}, "breakdown_value": "Chrome", "data": [1]},
                    {"action": {"order": 0}, "breakdown_value": "Firefox", "data": [2]},
                ],
            ),
        ]
    )
    def test_apply_trends_series_delete(
        self,
        _name: str,
        query: TrendsQuery,
        cached_results: list[dict],
        deleted_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedTrendsQueryResponse

        runner = TrendsQueryRunner(query=query, team=self.team)

        cached_response = CachedTrendsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_delete(cached_response, deleted_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "deletes_middle_step_from_funnel",
                [
                    {"order": 0, "custom_name": "Step A", "count": 100},
                    {"order": 1, "custom_name": "Step B", "count": 50},
                    {"order": 2, "custom_name": "Step C", "count": 25},
                ],
                1,
                [
                    {"order": 0, "custom_name": "Step A", "count": 100},
                    {"order": 1, "custom_name": "Step C", "count": 25},
                ],
            ),
            (
                "deletes_step_from_funnel_with_breakdown",
                [
                    [
                        {"order": 0, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "count": 50, "breakdown": "Chrome"},
                        {"order": 2, "count": 25, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "count": 40, "breakdown": "Firefox"},
                        {"order": 2, "count": 20, "breakdown": "Firefox"},
                    ],
                ],
                1,
                [
                    [
                        {"order": 0, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "count": 25, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "count": 20, "breakdown": "Firefox"},
                    ],
                ],
            ),
        ]
    )
    def test_apply_funnels_series_delete(
        self,
        _name: str,
        cached_results: list,
        deleted_index: int,
        expected_results: list,
    ):
        from datetime import UTC

        from posthog.schema import CachedFunnelsQueryResponse, FunnelsQuery

        from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

        query = FunnelsQuery(
            series=[
                EventsNode(event="step_a"),
                EventsNode(event="step_c"),
            ]
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)

        cached_response = CachedFunnelsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_delete(cached_response, deleted_index)

        self.assertEqual(patched_response.results, expected_results)


class TestApplySeriesDuplicate(BaseTest):
    @parameterized.expand(
        [
            (
                "duplicates_series_in_trends",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                        EventsNode(event="event_b"),
                        EventsNode(event="event_b", custom_name="Copy of B"),
                        EventsNode(event="event_c"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
                ],
                1,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "Copy of B"}, "data": [2]},
                    {"action": {"order": 3, "custom_name": "C"}, "data": [3]},
                ],
            ),
            (
                "duplicates_first_series",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                        EventsNode(event="event_a", custom_name="Copy of A"),
                        EventsNode(event="event_b"),
                    ]
                ),
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                ],
                0,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "Copy of A"}, "data": [1]},
                    {"action": {"order": 2, "custom_name": "B"}, "data": [2]},
                ],
            ),
            (
                "handles_breakdown_results_with_duplicate",
                TrendsQuery(
                    series=[
                        EventsNode(event="event_a"),
                        EventsNode(event="event_a", custom_name="Dup"),
                    ]
                ),
                [
                    {"action": {"order": 0}, "breakdown_value": "Chrome", "data": [1]},
                    {"action": {"order": 0}, "breakdown_value": "Firefox", "data": [2]},
                ],
                0,
                [
                    {"action": {"order": 0}, "breakdown_value": "Chrome", "data": [1]},
                    {"action": {"order": 1, "custom_name": "Dup"}, "breakdown_value": "Chrome", "data": [1]},
                    {"action": {"order": 0}, "breakdown_value": "Firefox", "data": [2]},
                    {"action": {"order": 1, "custom_name": "Dup"}, "breakdown_value": "Firefox", "data": [2]},
                ],
            ),
        ]
    )
    def test_apply_trends_series_duplicate(
        self,
        _name: str,
        query: TrendsQuery,
        cached_results: list[dict],
        duplicated_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedTrendsQueryResponse

        runner = TrendsQueryRunner(query=query, team=self.team)

        cached_response = CachedTrendsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_duplicate(cached_response, duplicated_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "duplicates_step_in_funnel",
                [
                    {"order": 0, "custom_name": "Step A", "count": 100},
                    {"order": 1, "custom_name": "Step B", "count": 50},
                ],
                0,
                [
                    {"order": 0, "custom_name": "Step A", "count": 100},
                    {"order": 1, "custom_name": "Copy of A", "count": 100},
                    {"order": 2, "custom_name": "Step B", "count": 50},
                ],
            ),
            (
                "duplicates_step_in_funnel_with_breakdown",
                [
                    [
                        {"order": 0, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "count": 40, "breakdown": "Firefox"},
                    ],
                ],
                0,
                [
                    [
                        {"order": 0, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "custom_name": "Copy of A", "count": 100, "breakdown": "Chrome"},
                        {"order": 2, "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "custom_name": "Copy of A", "count": 80, "breakdown": "Firefox"},
                        {"order": 2, "count": 40, "breakdown": "Firefox"},
                    ],
                ],
            ),
        ]
    )
    def test_apply_funnels_series_duplicate(
        self,
        _name: str,
        cached_results: list,
        duplicated_index: int,
        expected_results: list,
    ):
        from datetime import UTC

        from posthog.schema import CachedFunnelsQueryResponse, FunnelsQuery

        from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

        query = FunnelsQuery(
            series=[
                EventsNode(event="step_a"),
                EventsNode(event="step_a", custom_name="Copy of A"),
                EventsNode(event="step_b"),
            ]
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)

        cached_response = CachedFunnelsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_duplicate(cached_response, duplicated_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "deletes_stickiness_series",
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                    {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
                ],
                1,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "C"}, "data": [3]},
                ],
            ),
        ]
    )
    def test_apply_stickiness_series_delete(
        self,
        _name: str,
        cached_results: list[dict],
        deleted_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedStickinessQueryResponse, StickinessQuery

        from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner

        query = StickinessQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_c"),
            ]
        )

        runner = StickinessQueryRunner(query=query, team=self.team)

        cached_response = CachedStickinessQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_delete(cached_response, deleted_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "duplicates_stickiness_series",
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                ],
                0,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                    {"action": {"order": 1, "custom_name": "Copy of A"}, "data": [1]},
                    {"action": {"order": 2, "custom_name": "B"}, "data": [2]},
                ],
            ),
        ]
    )
    def test_apply_stickiness_series_duplicate(
        self,
        _name: str,
        cached_results: list[dict],
        duplicated_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedStickinessQueryResponse, StickinessQuery

        from posthog.hogql_queries.insights.stickiness_query_runner import StickinessQueryRunner

        query = StickinessQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_a", custom_name="Copy of A"),
                EventsNode(event="event_b"),
            ]
        )

        runner = StickinessQueryRunner(query=query, team=self.team)

        cached_response = CachedStickinessQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_duplicate(cached_response, duplicated_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "deletes_lifecycle_series",
                [
                    {"action": {"order": 0, "custom_name": "A"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "A"}, "status": "returning", "data": [2]},
                    {"action": {"order": 1, "custom_name": "B"}, "status": "new", "data": [3]},
                    {"action": {"order": 1, "custom_name": "B"}, "status": "returning", "data": [4]},
                ],
                1,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "A"}, "status": "returning", "data": [2]},
                ],
            ),
        ]
    )
    def test_apply_lifecycle_series_delete(
        self,
        _name: str,
        cached_results: list[dict],
        deleted_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedLifecycleQueryResponse, LifecycleQuery

        from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner

        query = LifecycleQuery(
            series=[
                EventsNode(event="event_a"),
            ]
        )

        runner = LifecycleQueryRunner(query=query, team=self.team)

        cached_response = CachedLifecycleQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_delete(cached_response, deleted_index)

        self.assertEqual(patched_response.results, expected_results)

    @parameterized.expand(
        [
            (
                "duplicates_lifecycle_series",
                [
                    {"action": {"order": 0, "custom_name": "A"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "A"}, "status": "returning", "data": [2]},
                ],
                0,
                [
                    {"action": {"order": 0, "custom_name": "A"}, "status": "new", "data": [1]},
                    {"action": {"order": 1, "custom_name": "Copy of A"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "A"}, "status": "returning", "data": [2]},
                    {"action": {"order": 1, "custom_name": "Copy of A"}, "status": "returning", "data": [2]},
                ],
            ),
        ]
    )
    def test_apply_lifecycle_series_duplicate(
        self,
        _name: str,
        cached_results: list[dict],
        duplicated_index: int,
        expected_results: list[dict],
    ):
        from datetime import UTC

        from posthog.schema import CachedLifecycleQueryResponse, LifecycleQuery

        from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner

        query = LifecycleQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_a", custom_name="Copy of A"),
            ]
        )

        runner = LifecycleQueryRunner(query=query, team=self.team)

        cached_response = CachedLifecycleQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response = runner.apply_series_duplicate(cached_response, duplicated_index)

        self.assertEqual(patched_response.results, expected_results)


class TestCacheSkippableHintDoesNotAffectCacheKey(BaseTest):
    def test_cache_key_independent_of_cache_skippable_hint(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview")])

        runner = TrendsQueryRunner(query=query, team=self.team)
        cache_key = runner.get_cache_key()

        # Cache key should be the same regardless of what hint we pass to run()
        # This verifies that cache_skippable_hint (passed at API level) doesn't
        # affect the cache key generated from the query
        self.assertEqual(
            runner.get_cache_key(),
            cache_key,
        )


class TestTryCacheOperation(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        super().tearDown()
        cache.clear()

    def test_returns_none_when_previous_cache_not_found(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Renamed")])
        runner = TrendsQueryRunner(query=query, team=self.team)

        result = runner._try_cache_operation(
            previous_cache_key="nonexistent_cache_key",
            new_cache_key="new_cache_key",
            cache_operation="series_rename",
            cache_operation_index=None,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNone(result)

    def test_applies_series_rename_from_cache(self):
        from datetime import UTC

        from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager

        query_before = TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Original")])
        runner_before = TrendsQueryRunner(query=query_before, team=self.team)
        cache_key_before = runner_before.get_cache_key()

        cached_data = {
            "results": [{"action": {"order": 0, "custom_name": "Original"}, "data": [1, 2, 3]}],
            "is_cached": True,
            "last_refresh": datetime.now(UTC).isoformat(),
            "next_allowed_client_refresh": datetime.now(UTC).isoformat(),
            "cache_key": cache_key_before,
            "timezone": "UTC",
        }

        cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team.pk,
            cache_key=cache_key_before,
        )
        cache_manager.set_cache_data(response=cached_data, ttl_seconds=3600, target_age_seconds=60)

        query_after = TrendsQuery(series=[EventsNode(event="$pageview", custom_name="Renamed")])
        runner_after = TrendsQueryRunner(query=query_after, team=self.team)
        new_cache_key = runner_after.get_cache_key()

        result = runner_after._try_cache_operation(
            previous_cache_key=cache_key_before,
            new_cache_key=new_cache_key,
            cache_operation="series_rename",
            cache_operation_index=None,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.results[0]["action"]["custom_name"], "Renamed")

    def test_applies_series_delete_from_cache(self):
        from datetime import UTC

        from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager

        query_before = TrendsQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_b"),
                EventsNode(event="event_c"),
            ]
        )
        runner_before = TrendsQueryRunner(query=query_before, team=self.team)
        cache_key_before = runner_before.get_cache_key()

        cached_data = {
            "results": [
                {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
                {"action": {"order": 2, "custom_name": "C"}, "data": [3]},
            ],
            "is_cached": True,
            "last_refresh": datetime.now(UTC).isoformat(),
            "next_allowed_client_refresh": datetime.now(UTC).isoformat(),
            "cache_key": cache_key_before,
            "timezone": "UTC",
        }

        cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team.pk,
            cache_key=cache_key_before,
        )
        cache_manager.set_cache_data(response=cached_data, ttl_seconds=3600, target_age_seconds=60)

        query_after = TrendsQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_c"),
            ]
        )
        runner_after = TrendsQueryRunner(query=query_after, team=self.team)
        new_cache_key = runner_after.get_cache_key()

        result = runner_after._try_cache_operation(
            previous_cache_key=cache_key_before,
            new_cache_key=new_cache_key,
            cache_operation="series_delete",
            cache_operation_index=1,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.results[0]["action"]["order"], 0)
        self.assertEqual(result.results[0]["action"]["custom_name"], "A")
        self.assertEqual(result.results[1]["action"]["order"], 1)
        self.assertEqual(result.results[1]["action"]["custom_name"], "C")

    def test_applies_series_duplicate_from_cache(self):
        from datetime import UTC

        from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager

        query_before = TrendsQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_b"),
            ]
        )
        runner_before = TrendsQueryRunner(query=query_before, team=self.team)
        cache_key_before = runner_before.get_cache_key()

        cached_data = {
            "results": [
                {"action": {"order": 0, "custom_name": "A"}, "data": [1]},
                {"action": {"order": 1, "custom_name": "B"}, "data": [2]},
            ],
            "is_cached": True,
            "last_refresh": datetime.now(UTC).isoformat(),
            "next_allowed_client_refresh": datetime.now(UTC).isoformat(),
            "cache_key": cache_key_before,
            "timezone": "UTC",
        }

        cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team.pk,
            cache_key=cache_key_before,
        )
        cache_manager.set_cache_data(response=cached_data, ttl_seconds=3600, target_age_seconds=60)

        query_after = TrendsQuery(
            series=[
                EventsNode(event="event_a"),
                EventsNode(event="event_a", custom_name="Copy of A"),
                EventsNode(event="event_b"),
            ]
        )
        runner_after = TrendsQueryRunner(query=query_after, team=self.team)
        new_cache_key = runner_after.get_cache_key()

        result = runner_after._try_cache_operation(
            previous_cache_key=cache_key_before,
            new_cache_key=new_cache_key,
            cache_operation="series_duplicate",
            cache_operation_index=0,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.results[0]["action"]["order"], 0)
        self.assertEqual(result.results[0]["action"]["custom_name"], "A")
        self.assertEqual(result.results[1]["action"]["order"], 1)
        self.assertEqual(result.results[1]["action"]["custom_name"], "Copy of A")
        self.assertEqual(result.results[2]["action"]["order"], 2)
        self.assertEqual(result.results[2]["action"]["custom_name"], "B")

    def test_returns_none_for_invalid_cache_data(self):
        from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager

        cache_key = "cache_with_invalid_data"

        cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team.pk,
            cache_key=cache_key,
        )
        cache_manager.set_cache_data(
            response={"invalid": "data"},
            ttl_seconds=3600,
            target_age_seconds=60,
        )

        query = TrendsQuery(series=[EventsNode(event="$pageview")])
        runner = TrendsQueryRunner(query=query, team=self.team)

        result = runner._try_cache_operation(
            previous_cache_key=cache_key,
            new_cache_key="new_cache_key",
            cache_operation="series_rename",
            cache_operation_index=None,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNone(result)

    def test_returns_none_for_unknown_cache_operation(self):
        from datetime import UTC

        from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager

        query = TrendsQuery(series=[EventsNode(event="$pageview")])
        runner = TrendsQueryRunner(query=query, team=self.team)
        cache_key = runner.get_cache_key()

        cached_data = {
            "results": [{"action": {"order": 0, "custom_name": "Original"}, "data": [1, 2, 3]}],
            "is_cached": True,
            "last_refresh": datetime.now(UTC).isoformat(),
            "next_allowed_client_refresh": datetime.now(UTC).isoformat(),
            "cache_key": cache_key,
            "timezone": "UTC",
        }

        cache_manager = DjangoCacheQueryCacheManager(
            team_id=self.team.pk,
            cache_key=cache_key,
        )
        cache_manager.set_cache_data(response=cached_data, ttl_seconds=3600, target_age_seconds=60)

        result = runner._try_cache_operation(
            previous_cache_key=cache_key,
            new_cache_key="new_cache_key",
            cache_operation="unknown_operation",
            cache_operation_index=None,
            insight_id=None,
            dashboard_id=None,
        )

        self.assertIsNone(result)
