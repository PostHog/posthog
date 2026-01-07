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

    def test_does_not_patch_funnels_query(self):
        """FunnelsQuery stores custom_name at top level of step, not nested under action.
        Patching should be skipped for non-TrendsQuery types."""
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

        original_results = [
            {"name": "step1", "custom_name": "Original Step 1", "order": 0, "count": 100},
            {"name": "step2", "custom_name": "Original Step 2", "order": 1, "count": 50},
        ]

        cached_response = CachedFunnelsQueryResponse(
            results=[original_results],
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, [original_results])
        self.assertFalse(was_modified)

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
