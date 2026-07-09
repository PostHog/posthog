from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BounceRatePageViewMode,
    CacheMissResponse,
    CurrencyCode,
    DataTableNode,
    DataVisualizationNode,
    EventsNode,
    HogQLQuery,
    HogQLQueryModifiers,
    InCohortVia,
    InlineCohortCalculation,
    InsightVizNode,
    IntervalType,
    MaterializationMode,
    PersonsArgMaxVersion,
    PersonsOnEventsMode,
    QueryLogTags,
    SessionsV2JoinMode,
    SessionTableVersion,
    TestBasicQueryResponse as TheTestBasicQueryResponse,
    TestCachedBasicQueryResponse as TheTestCachedBasicQueryResponse,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError, ResolutionError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import (
    AnalyticsQueryRunner,
    ExecutionMode,
    QueryRunner,
    QueryRunnerWithHogQLContext,
    get_query_runner,
    shared_insights_execution_mode,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team, WeekStartDay
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlError

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass
from posthog.slo.types import SloOutcome

from products.customer_analytics.backend.facade.constants import DEFAULT_ACTIVITY_EVENT
from products.revenue_analytics.backend.hogql_queries.test.data.structure import REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT

MARKETING_ANALYTICS_SOURCES_MAP_SAMPLE = {
    "01977f7b-7f29-0000-a028-7275d1a767a4": {
        "cost": "cost",
        "date": "date",
        "clicks": "clicks",
        "source": "_metadata_launched_at",
        "campaign": "campaignname",
        "currency": "const:USD",
        "impressions": "impressions",
    },
}


class TheTestQuery(BaseModel):
    kind: Literal["TestQuery"] = "TestQuery"
    some_attr: str
    other_attr: Optional[list[Any]] = []
    tags: QueryLogTags | None = None


class TestQueryRunner(BaseTest):
    maxDiff = None

    def tearDown(self):
        super().tearDown()
        cache.clear()

    def setup_test_query_runner_class(self, base: type[QueryRunner] = QueryRunner):
        """Setup required methods and attributes of the abstract base class."""

        class TestQueryRunner(base):  # type: ignore[misc, valid-type]
            query: TheTestQuery
            cached_response: TheTestCachedBasicQueryResponse

            def _calculate(self):
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

    def test_sync_warning_attach_preserves_other_warning_kinds(self):
        # The accumulator attach replaces the response's warnings with the collected sync warnings.
        # Access control warnings ride the same shared field and were silently dropped whenever a
        # sync warning was present.
        from posthog.schema import AccessControlFilterWarning, DataWarehouseSyncWarning

        from posthog.hogql.warehouse_warnings import record_warnings

        TestQueryRunner = self.setup_test_query_runner_class()
        sync_warning = DataWarehouseSyncWarning(
            table_name="paid_bills",
            schema_name="paid_bills",
            source_type="Stripe",
            status="Failed",
            message="sync failed",
        )
        ac_warning = AccessControlFilterWarning(
            resources=["insight"], message="Results may exclude insights you don't have access to"
        )

        def calculate_with_warnings(_self):
            record_warnings([sync_warning])
            response = TheTestBasicQueryResponse(results=[])
            response.warnings = [ac_warning]
            return response

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)
        with mock.patch.object(TestQueryRunner, "_calculate", autospec=True, side_effect=calculate_with_warnings):
            response = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        warnings = [w if isinstance(w, dict) else w.model_dump() for w in response.warnings or []]
        assert any(w.get("table_name") == "paid_bills" for w in warnings)
        assert any(w.get("resources") == ["insight"] for w in warnings)

    def test_calculate_runs_validators_before_calculation(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        validation_rule = mock.MagicMock()
        validation_rule.validate.side_effect = ValidationError("Validation failed")
        TestQueryRunner.validators = lambda self: (validation_rule,)
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with mock.patch.object(TestQueryRunner, "_calculate", autospec=True) as mock_calculate:
            with self.assertRaises(ValidationError) as context:
                runner.calculate()

        self.assertIn("Validation failed", str(context.exception))
        validation_rule.validate.assert_called_once_with(runner.validation_context)
        mock_calculate.assert_not_called()

    def test_init_with_query_instance(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query=TheTestQuery(some_attr="bla"), team=self.team)

        self.assertEqual(runner.query, TheTestQuery(some_attr="bla"))

    def test_init_with_query_dict(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        self.assertEqual(runner.query, TheTestQuery(some_attr="bla"))

    @parameterized.expand(
        [
            [
                DataVisualizationNode(source=HogQLQuery(query="SELECT 1")),
                HogQLQuery(query="SELECT 1"),
            ],
            [
                {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "SELECT 1"}},
                HogQLQuery(query="SELECT 1"),
            ],
            [
                DataTableNode(source=HogQLQuery(query="SELECT 2")),
                HogQLQuery(query="SELECT 2"),
            ],
            [
                {"kind": "DataTableNode", "source": {"kind": "HogQLQuery", "query": "SELECT 2"}},
                HogQLQuery(query="SELECT 2"),
            ],
            [
                InsightVizNode(source=TrendsQuery(series=[EventsNode(event="$pageview")])),
                TrendsQuery(series=[EventsNode(event="$pageview")]),
            ],
            [
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                },
                TrendsQuery(series=[EventsNode(event="$pageview")]),
            ],
        ]
    )
    def test_get_query_runner_uses_source_query_for_wrappers(self, query, expected_source_query):
        runner = get_query_runner(query=query, team=self.team)

        self.assertEqual(runner.query, expected_source_query)

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
                "inlineCohortCalculation": InlineCohortCalculation.AUTO,
                "materializationMode": MaterializationMode.LEGACY_NULL_AS_NULL,
                "optimizeJoinedFilters": False,
                "optimizeProjections": True,
                "personsArgMaxVersion": PersonsArgMaxVersion.AUTO,
                "personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                "sessionIdPushdown": False,
                "sessionPropertyPreAggregation": False,
                "sessionTableVersion": SessionTableVersion.AUTO,
                "sessionsV2JoinMode": SessionsV2JoinMode.UUID,
                "useMaterializedViews": True,
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
                            "currency": "const:USD",
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
        assert cache_key == "cache_42_13ab830e775c41ee3ae4b45c386e6064d74eec55fb93092732c0bb305d7e980f"

    def test_cache_key_runner_subclass(self):
        TestQueryRunner = self.setup_test_query_runner_class()

        class TestSubclassQueryRunner(TestQueryRunner):  # type: ignore[misc, valid-type]
            pass

        # set the pk directly as it affects the hash in the _cache_key call
        team = Team.objects.create(pk=42, organization=self.organization)

        runner = TestSubclassQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_42_b624e873acbdc9829f0973b4dc14424bb26e3b5c36c11387ce24e9ff3bea2a00"

    def test_cache_key_different_timezone(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        team = Team.objects.create(pk=42, organization=self.organization)
        team.timezone = "Europe/Vienna"
        team.save()

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=team)

        cache_key = runner.get_cache_key()
        assert cache_key == "cache_42_473689ec17cc982383519776503e498bd0e44f16e6b6f0073412599254a69aba"

    def test_cache_payload_omits_object_restrictions_when_unrestricted(self):
        TestQueryRunner = self.setup_test_query_runner_class()
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team, user=self.user)

        assert "restricted_objects" not in runner.get_cache_payload()

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

    @parameterized.expand(
        [
            ("success", None, None, 1, 0),
            ("error_result", "error", None, 1, 0),
            ("exception", "raise", ValueError, 0, 1),
        ]
    )
    def test_query_execution_metrics(self, _name, calculate_mode, expected_exception, success_delta, failure_delta):
        from posthog.clickhouse.query_tagging import reset_query_tags
        from posthog.hogql_queries.query_runner import QUERY_EXECUTION_DURATION, QUERY_EXECUTION_TOTAL

        # Sibling tests in this class invoke real HogQL runners that flip
        # `contains_user_hogql` on the ContextVar; reset so we observe "false".
        reset_query_tags()

        TestQueryRunner = self.setup_test_query_runner_class()
        if calculate_mode == "error":
            TestQueryRunner.calculate = lambda self: TheTestBasicQueryResponse(results=[], error="Some error occurred")
        elif calculate_mode == "raise":

            def calculate_raises(self):
                raise ValueError("Query execution failed")

            TestQueryRunner.calculate = calculate_raises
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        before_success = QUERY_EXECUTION_TOTAL.labels(
            query_type="TestQuery", category="success", error_type="none", contains_user_hogql="false"
        )._value.get()
        before_failure = QUERY_EXECUTION_TOTAL.labels(
            query_type="TestQuery", category="error", error_type="ValueError", contains_user_hogql="false"
        )._value.get()
        before_duration_sum = QUERY_EXECUTION_DURATION.labels(query_type="TestQuery")._sum.get()

        if expected_exception:
            with pytest.raises(expected_exception):
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        else:
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        assert (
            QUERY_EXECUTION_TOTAL.labels(
                query_type="TestQuery", category="success", error_type="none", contains_user_hogql="false"
            )._value.get()
            - before_success
            == success_delta
        )
        assert (
            QUERY_EXECUTION_TOTAL.labels(
                query_type="TestQuery", category="error", error_type="ValueError", contains_user_hogql="false"
            )._value.get()
            - before_failure
            == failure_delta
        )
        assert QUERY_EXECUTION_DURATION.labels(query_type="TestQuery")._sum.get() > before_duration_sum

    @parameterized.expand([("success_path", None), ("error_path", ValueError)])
    def test_query_execution_metric_labels_with_contains_user_hogql(
        self, _name: str, expected_exception: Optional[type[Exception]]
    ) -> None:
        # Verifies the `contains_user_hogql` label flows from the canonical
        # `QueryTags.contains_user_hogql` tag (set by `tag_contains_user_hogql()`
        # at HogQL parse sites) rather than being recomputed schema-side.
        from posthog.clickhouse.query_tagging import reset_query_tags, tag_contains_user_hogql
        from posthog.hogql_queries.query_runner import QUERY_EXECUTION_TOTAL

        TestQueryRunner = self.setup_test_query_runner_class()

        if expected_exception is None:

            def calculate_tags(self: Any) -> Any:
                tag_contains_user_hogql()
                return TheTestBasicQueryResponse(results=[])

            TestQueryRunner.calculate = calculate_tags
            label_kwargs = {
                "query_type": "TestQuery",
                "category": "success",
                "error_type": "none",
                "contains_user_hogql": "true",
            }
        else:

            def calculate_tags_then_raise(self: Any) -> Any:
                tag_contains_user_hogql()
                raise ValueError("boom")

            TestQueryRunner.calculate = calculate_tags_then_raise
            label_kwargs = {
                "query_type": "TestQuery",
                "category": "error",
                "error_type": "ValueError",
                "contains_user_hogql": "true",
            }

        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)
        # ContextVar persists across tests; reset both before (so we observe a real
        # transition false→true via calculate) and after (so siblings don't see "true").
        reset_query_tags()
        before = QUERY_EXECUTION_TOTAL.labels(**label_kwargs)._value.get()

        try:
            if expected_exception:
                with pytest.raises(expected_exception):
                    runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            else:
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

            assert QUERY_EXECUTION_TOTAL.labels(**label_kwargs)._value.get() - before == 1
        finally:
            reset_query_tags()

    @parameterized.expand(
        [
            (
                "user_access_control_error",
                lambda: UserAccessControlError("query", "viewer", None),
                SloOutcome.SUCCESS,
                "user_error",
                False,
            ),
            ("concurrency_limit_exceeded", ConcurrencyLimitExceeded, SloOutcome.SUCCESS, "rate_limited", False),
            (
                "user_hogql_query_error",
                lambda: QueryError("Can't select a table when a column is expected: postgres_waitlist_entries"),
                SloOutcome.SUCCESS,
                "user_error",
                False,
            ),
            (
                # ClickHouse-raised user-safe error (code 60 = UNKNOWN_TABLE), e.g. a query
                # referencing a deleted warehouse table — must not reach error tracking.
                "user_facing_ch_query_error",
                lambda: ExposedCHQueryError("Unknown table ae_event_people", code=60),
                SloOutcome.SUCCESS,
                "user_error",
                False,
            ),
            (
                # Internal (non-exposed) HogQL errors are server faults and must stay captured.
                "internal_hogql_resolution_error",
                lambda: ResolutionError("Unable to resolve field: ae_event_people"),
                SloOutcome.FAILURE,
                "error",
                True,
            ),
            ("unclassified_value_error", ValueError, SloOutcome.FAILURE, "error", True),
        ]
    )
    def test_run_classifies_slo_error_at_except_boundary(
        self, _name, exception_factory, expected_outcome, expected_error_category, expected_captured
    ):
        TestQueryRunner = self.setup_test_query_runner_class()
        raised_exc = exception_factory()

        def calculate_raises(self):
            raise raised_exc

        TestQueryRunner.calculate = calculate_raises
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with (
            mock.patch("posthog.slo.context.emit_slo_completed") as mock_emit_slo_completed,
            mock.patch("posthog.hogql_queries.query_runner.capture_exception") as mock_capture_exception,
        ):
            with pytest.raises(type(raised_exc)):
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        mock_emit_slo_completed.assert_called_once()
        completed_kwargs = mock_emit_slo_completed.call_args.kwargs
        assert completed_kwargs["properties"].outcome == expected_outcome
        assert completed_kwargs["extra_properties"]["error_category"] == expected_error_category

        # User-input errors (SUCCESS outcome) must not be captured to error tracking; only FAILURE
        # outcomes are. This is what keeps benign HogQL query errors out of error tracking.
        captured = any(call.args and call.args[0] is raised_exc for call in mock_capture_exception.call_args_list)
        assert captured == expected_captured

    def test_query_execution_metrics_not_recorded_on_cache_hit(self):
        from posthog.clickhouse.query_tagging import reset_query_tags
        from posthog.hogql_queries.query_runner import QUERY_EXECUTION_DURATION, QUERY_EXECUTION_TOTAL

        # Sibling tests may have flipped `contains_user_hogql` on the ContextVar.
        reset_query_tags()

        TestQueryRunner = self.setup_test_query_runner_class()
        runner = TestQueryRunner(query={"some_attr": "bla"}, team=self.team)

        with freeze_time(datetime(2023, 2, 4, 13, 37, 42)):
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        before_success = QUERY_EXECUTION_TOTAL.labels(
            query_type="TestQuery", category="success", error_type="none", contains_user_hogql="false"
        )._value.get()
        before_failure = QUERY_EXECUTION_TOTAL.labels(
            query_type="TestQuery", category="error", error_type="ValueError", contains_user_hogql="false"
        )._value.get()
        before_duration_sum = QUERY_EXECUTION_DURATION.labels(query_type="TestQuery")._sum.get()

        # Cache is fresh (< 10 min old), so this hits the cache without recalculating
        with freeze_time(datetime(2023, 2, 4, 13, 38, 0)):
            runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        assert (
            QUERY_EXECUTION_TOTAL.labels(
                query_type="TestQuery", category="success", error_type="none", contains_user_hogql="false"
            )._value.get()
            == before_success
        )
        assert (
            QUERY_EXECUTION_TOTAL.labels(
                query_type="TestQuery", category="error", error_type="ValueError", contains_user_hogql="false"
            )._value.get()
            == before_failure
        )
        assert QUERY_EXECUTION_DURATION.labels(query_type="TestQuery")._sum.get() == before_duration_sum

    @parameterized.expand(
        [
            ("success", None, None, 1, 0),
            ("error_result", "error", None, 1, 0),
            ("exception", "raise", ValueError, 0, 1),
        ]
    )
    def test_survey_query_execution_metrics(
        self, _name, calculate_mode, expected_exception, success_delta, failure_delta
    ):
        from posthog.hogql_queries.query_runner import SURVEY_QUERY_EXECUTION_DURATION, SURVEY_QUERY_EXECUTION_TOTAL

        TestQueryRunner = self.setup_test_query_runner_class()
        query_labels = {
            "query_type": "TestQuery",
            "query_name": "test_query_name",
        }
        if calculate_mode == "error":
            TestQueryRunner.calculate = lambda self: TheTestBasicQueryResponse(results=[], error="Some error occurred")
        elif calculate_mode == "raise":

            def calculate_raises(self):
                raise ValueError("Query execution failed")

            TestQueryRunner.calculate = calculate_raises

        runner = TestQueryRunner(
            query={
                "some_attr": "bla",
                "tags": {"productKey": "surveys", "scene": "TestScene", "name": "test_query_name"},
            },
            team=self.team,
        )

        before_success = SURVEY_QUERY_EXECUTION_TOTAL.labels(
            **query_labels, category="success", error_type="none"
        )._value.get()
        before_failure = SURVEY_QUERY_EXECUTION_TOTAL.labels(
            **query_labels, category="error", error_type="ValueError"
        )._value.get()
        before_duration_sum = SURVEY_QUERY_EXECUTION_DURATION.labels(**query_labels)._sum.get()

        if expected_exception:
            with pytest.raises(expected_exception):
                runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        else:
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        assert (
            SURVEY_QUERY_EXECUTION_TOTAL.labels(**query_labels, category="success", error_type="none")._value.get()
            - before_success
            == success_delta
        )
        assert (
            SURVEY_QUERY_EXECUTION_TOTAL.labels(**query_labels, category="error", error_type="ValueError")._value.get()
            - before_failure
            == failure_delta
        )
        assert SURVEY_QUERY_EXECUTION_DURATION.labels(**query_labels)._sum.get() > before_duration_sum


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

        from products.product_analytics.backend.hogql_queries.stickiness.stickiness_query_runner import (
            StickinessQueryRunner,
        )

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

        from posthog.hogql_queries.insights.lifecycle.lifecycle_query_runner import LifecycleQueryRunner

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


class TestSharedInsightsExecutionMode(BaseTest):
    @parameterized.expand(
        [
            # name, execution_mode, last_refresh_offset (None = no signal, timedelta = age), expected_mode
            (
                "force_blocking_no_last_refresh_downgrades",
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                None,
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ),
            (
                "force_blocking_just_refreshed_downgrades",
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                timedelta(seconds=10),
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ),
            (
                "force_blocking_just_under_threshold_downgrades",
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                timedelta(minutes=29, seconds=59),
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ),
            (
                "force_blocking_at_threshold_passes_through",
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                timedelta(minutes=30),
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            ),
            (
                "force_blocking_long_stale_passes_through",
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                timedelta(hours=24),
                ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            ),
            (
                "cache_only_remaps_to_extended_async",
                ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                timedelta(seconds=10),
                ExecutionMode.EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE,
            ),
            (
                "recent_cache_async_passes_through",
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                None,
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
            ),
            (
                "blocking_if_stale_passes_through",
                # Used by the shared-notebook inline query payload builder. Must pass through so
                # cold-cache loads block and return real results — falling back to async would
                # ship a CacheMissResponse to the frontend, which renders the "unsupported node"
                # placeholder until a later reload picks up the warmed cache.
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                None,
                ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ),
        ]
    )
    def test_shared_insights_execution_mode(
        self,
        _name: str,
        execution_mode: ExecutionMode,
        last_refresh_offset: timedelta | None,
        expected_mode: ExecutionMode,
    ) -> None:
        last_refresh = None if last_refresh_offset is None else datetime.now(UTC) - last_refresh_offset
        result = shared_insights_execution_mode(execution_mode, last_refresh=last_refresh)
        self.assertEqual(result, expected_mode)


@pytest.mark.ee
class TestQueryRunnerAccessControlFingerprint(BaseTest):
    """The HogQL cache key must partition on object- and resource-level access control, otherwise
    two users with different visibility could share a cached (filtered) result."""

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        # Object/resource AC only applies to non-admins.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def tearDown(self):
        super().tearDown()
        cache.clear()

    RUNNER_BASES = [("analytics", AnalyticsQueryRunner), ("ctx", QueryRunnerWithHogQLContext)]

    def _runner(self, user, base=QueryRunnerWithHogQLContext, queried_resources=None):
        # `queried_resources` is the result we want the fingerprint to compute; pick a query that
        # produces it: an unparseable query reads as None (fail closed), "select 1" reads no AC table.
        query = HogQLQuery(query="select from from" if queried_resources is None else "select 1")

        class _Runner(base):  # type: ignore[valid-type, misc]  # base is a runtime-parameterized class
            query: HogQLQuery
            cached_response: TheTestCachedBasicQueryResponse

            def _calculate(self):
                return TheTestBasicQueryResponse(results=[])

            def to_query(self) -> ast.SelectQuery:
                return ast.SelectQuery(select=[])

            def _refresh_frequency(self) -> timedelta:
                return timedelta(minutes=4)

            def _is_stale(self, last_refresh, lazy: bool = False, *args, **kwargs) -> bool:
                return False

        return _Runner(query=query, team=self.team, user=user)

    def _ac(self, resource, resource_id=None, access_level="none", organization_member=None):
        ac, _ = AccessControl.objects.get_or_create(
            team=self.team, resource=resource, resource_id=resource_id, organization_member=organization_member
        )
        ac.access_level = access_level
        ac.save()
        return ac

    @parameterized.expand(RUNNER_BASES)
    def test_resource_grant_changes_cache_key(self, _name, base):
        self._ac(resource="notebook", access_level="none")
        key_denied = self._runner(self.user, base).get_cache_key()

        self._ac(resource="notebook", access_level="editor")
        key_granted = self._runner(self.user, base).get_cache_key()

        assert key_denied != key_granted

    @parameterized.expand(RUNNER_BASES)
    def test_fingerprint_covers_scopes_outside_the_legacy_resource_list(self, _name, base):
        # System tables declare access_scopes (e.g. batch_export, alert, annotation) that the old
        # hand-maintained blocked_resources tuple missed - a deny removed the table from the schema
        # but left the cache key unchanged. blocked_resources is now derived from the actual rows,
        # so any denied scope must show up in the fingerprint.
        scopes = {"batch_export", "alert", "annotation"}
        for scope in scopes:
            self._ac(resource=scope, access_level="none")
        restricted = set(self._runner(self.user, base).get_cache_payload().get("restricted_resources") or [])
        assert scopes <= restricted

    @parameterized.expand(RUNNER_BASES)
    def test_object_grant_changes_cache_key(self, _name, base):
        from products.notebooks.backend.models import Notebook

        # Resource-level access granted so we isolate the object-level effect.
        self._ac(resource="notebook", access_level="editor")
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="N")

        blocking_ac = self._ac(
            resource="notebook",
            resource_id=str(notebook.id),
            access_level="none",
            organization_member=self.organization_membership,
        )
        runner = self._runner(self.user, base)
        assert "restricted_objects" in runner.get_cache_payload()
        key_blocked = runner.get_cache_key()

        blocking_ac.delete()
        key_unblocked = self._runner(self.user, base).get_cache_key()

        assert key_blocked != key_unblocked

    @parameterized.expand(RUNNER_BASES)
    def test_admin_has_no_restrictions_but_userless_fails_closed(self, _name, base):
        self._ac(resource="notebook", access_level="none")

        # Org admin bypasses object/resource AC - no restriction keys, so they share the
        # unrestricted cache partition.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_payload = self._runner(self.user, base).get_cache_payload()
        assert "restricted_objects" not in admin_payload
        assert "restricted_resources" not in admin_payload

        # Userless runs fail-closed (see no system.* tables), so they must partition separately
        # from the admin's unrestricted result.
        no_user_payload = self._runner(None, base).get_cache_payload()
        assert no_user_payload["restricted_resources"] == ["*"]
        assert self._runner(None, base).get_cache_key() != self._runner(self.user, base).get_cache_key()

    def test_hogql_query_runner_partitions_cache_on_access_control(self):
        # Raw HogQL is the only way to reach access-controlled system.* tables.
        query = {"kind": "HogQLQuery", "query": "select * from system.notebooks"}

        self._ac(resource="notebook", access_level="none")
        denied_runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)
        assert "notebook" in (denied_runner.get_cache_payload().get("restricted_resources") or [])
        key_denied = denied_runner.get_cache_key()

        self._ac(resource="notebook", access_level="editor")
        key_granted = HogQLQueryRunner(query=query, team=self.team, user=self.user).get_cache_key()

        assert key_denied != key_granted

    @parameterized.expand(RUNNER_BASES)
    def test_query_reading_no_access_controlled_tables_shares_cache(self, _name, base):
        # A query that reads no access-controlled table is principal-independent: a denied user, a
        # granted user, and userless cache warming must all land in the same (unpartitioned) entry.
        self._ac(resource="notebook", access_level="none")
        payload = self._runner(self.user, base, queried_resources=set()).get_cache_payload()
        assert "restricted_resources" not in payload
        assert "restricted_objects" not in payload

        shared_key = self._runner(self.user, base, queried_resources=set()).get_cache_key()
        assert self._runner(None, base, queried_resources=set()).get_cache_key() == shared_key

    def test_no_access_controlled_tables_skips_the_preload(self):
        # The point of the branch: a query that reads no access-controlled table must not even
        # load access control
        self._ac(resource="notebook", access_level="none")
        runner = self._runner(self.user, AnalyticsQueryRunner, queried_resources=set())
        with CaptureQueriesContext(connection) as ctx:
            runner.get_cache_key()
        ac_queries = [q["sql"] for q in ctx.captured_queries if "ee_accesscontrol" in q["sql"]]
        assert ac_queries == [], ac_queries

    def test_hogql_fingerprint_partitions_only_on_queried_tables(self):
        # Two denied resources, but the query only reads notebooks - so only that scope partitions.
        self._ac(resource="notebook", access_level="none")
        self._ac(resource="survey", access_level="none")
        query = {"kind": "HogQLQuery", "query": "select * from system.notebooks"}
        runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)

        restricted = set(runner.get_cache_payload().get("restricted_resources") or [])
        assert "notebook" in restricted  # queried and denied
        assert "survey" not in restricted  # denied but not read by the query

    def test_resource_deny_on_parent_partitions_inherited_child_table(self):
        # system.accounts uses the "account" scope, which inherits from "customer_analytics".
        # A deny on the parent must still partition a query that reads the child table - otherwise the
        # schema filter denies it but the cache key doesn't, and a denied user gets a cached result.
        self._ac(resource="customer_analytics", access_level="none")
        query = {"kind": "HogQLQuery", "query": "select * from system.accounts"}
        runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)

        restricted = set(runner.get_cache_payload().get("restricted_resources") or [])
        assert "account" in restricted  # denied via the inherited parent customer_analytics

    def test_querying_access_controlled_tables_issues_one_preload(self):
        # has_resource_access (incl. the inheritance recursion account -> customer_analytics) resolves
        # against the in-memory preload, so reading several access-controlled tables still issues exactly
        # one ee_accesscontrol query - no per-scope N+1.
        self._ac(resource="customer_analytics", access_level="none")
        self._ac(resource="notebook", access_level="none")
        query = {"kind": "HogQLQuery", "query": "select * from system.accounts, system.notebooks, system.surveys"}
        runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)

        with CaptureQueriesContext(connection) as ctx:
            runner.get_cache_key()

        ac_queries = [q["sql"] for q in ctx.captured_queries if "ee_accesscontrol" in q["sql"]]
        assert len(ac_queries) == 1, ac_queries

    def test_object_level_deny_on_queried_resource_partitions_cache(self):
        from products.notebooks.backend.models import Notebook

        # Resource-level access granted so we isolate the object-level effect.
        self._ac(resource="notebook", access_level="editor")
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="N")
        query = {"kind": "HogQLQuery", "query": "select * from system.notebooks"}
        key_unblocked = HogQLQueryRunner(query=query, team=self.team, user=self.user).get_cache_key()

        # Deny this specific notebook object - the query reads notebooks, so it must partition.
        self._ac(
            resource="notebook",
            resource_id=str(notebook.id),
            access_level="none",
            organization_member=self.organization_membership,
        )
        runner = HogQLQueryRunner(query=query, team=self.team, user=self.user)
        assert runner.get_cache_payload().get("restricted_objects", {}).get("notebook") == [str(notebook.id)]
        assert runner.get_cache_key() != key_unblocked

    def test_object_level_deny_on_unqueried_resource_is_ignored(self):
        from products.notebooks.backend.models import Notebook

        # Deny a specific notebook object, but the query reads surveys - the deny is irrelevant.
        self._ac(resource="notebook", access_level="editor")
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="N")
        self._ac(
            resource="notebook",
            resource_id=str(notebook.id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        query = {"kind": "HogQLQuery", "query": "select * from system.surveys"}
        payload = HogQLQueryRunner(query=query, team=self.team, user=self.user).get_cache_payload()
        assert "restricted_objects" not in payload  # notebook object deny doesn't touch a surveys query

    def test_run_recomputes_fingerprint_when_user_changes(self):
        # run(user=...) swaps the user after construction; the snapshot must rebuild for the new user.
        other_user = self._create_user("other@posthog.com")
        other_membership = other_user.organization_memberships.get(organization=self.organization)
        self._ac(resource="notebook", access_level="none")
        # Personal grant for other_user only - the two users must land in different cache partitions.
        self._ac(resource="notebook", access_level="editor", organization_member=other_membership)

        runner = self._runner(self.user, AnalyticsQueryRunner)
        key_restricted = runner.get_cache_key()

        runner.user = other_user
        runner._on_user_changed()
        key_granted = runner.get_cache_key()

        assert key_restricted != key_granted

    def test_fingerprint_and_schema_filter_share_one_instance(self):
        # The ctx runner's fingerprint reuses the instance create_for preloaded on the database, so
        # the cache key and schema filtering resolve from the same rows (no drift).
        runner = self._runner(self.user)
        assert runner.database.user_access_control is runner.user_access_control

    def test_cache_payload_preloads_access_controls_once(self):
        # The memoized snapshot means both fingerprint helpers + repeated calls share one preload.
        self._ac(resource="notebook", access_level="none")
        runner = self._runner(self.user, AnalyticsQueryRunner)

        with CaptureQueriesContext(connection) as ctx:
            runner.get_cache_key()
            runner.get_cache_key()

        ac_queries = [q["sql"] for q in ctx.captured_queries if "ee_accesscontrol" in q["sql"]]
        assert len(ac_queries) == 1, ac_queries

    def test_run_issues_bounded_access_control_queries(self):
        """End-to-end: building the database (schema filtering) plus computing the cache key issues
        exactly two access-control queries - one for property-level AC and one shared bulk fetch for
        resource/object AC - regardless of how many resources/objects/system tables exist. Schema
        filtering must reuse the fingerprint's UserAccessControl, not issue its own ee_accesscontrol
        query."""
        from products.access_control.backend.property_access_control import restriction_cache_scope

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL},
        ]
        self.organization.save()
        self._ac(resource="notebook", access_level="none")

        with (
            restriction_cache_scope(),
            CaptureQueriesContext(connection) as ctx,
        ):
            runner = self._runner(self.user)
            runner.get_cache_key()

        # Guard against a false pass: prove schema filtering actually ran and consulted access control
        # (it removed the notebook-scoped system table for this denied user). Without this, a single
        # ee_accesscontrol query could come from the fingerprint alone and the "shared fetch" claim
        # would be untested.
        assert "system.notebooks" in runner.database._denied_tables

        sqls = [q["sql"] for q in ctx.captured_queries]
        resource_object_ac = [s for s in sqls if "ee_accesscontrol" in s]
        property_ac = [s for s in sqls if "access_control_propertyaccesscontrol" in s]

        # One shared bulk fetch for resource/object AC (schema filtering + fingerprint), one for property AC.
        assert len(resource_object_ac) == 1, resource_object_ac
        assert len(property_ac) == 1, property_ac

    def test_create_for_reuses_preloaded_user_access_control(self):
        # HogQLQueryRunner (a base AnalyticsQueryRunner) builds its database lazily inside
        # execute_hogql_query, so it can't share via self.database like the ctx runner does. Instead
        # it hands its warm fingerprint snapshot to create_for, which must reuse it rather than issue
        # a second ee_accesscontrol fetch. This is the base-runner equivalent of the ctx-runner budget
        # asserted in test_run_issues_bounded_access_control_queries.
        self._ac(resource="notebook", access_level="none")
        user_access_control = UserAccessControl(user=self.user, team=self.team)
        # Warm the snapshot - the single bulk fetch the fingerprint already paid for.
        _ = user_access_control.blocked_resources

        with CaptureQueriesContext(connection) as ctx:
            database = Database.create_for(team=self.team, user=self.user, user_access_control=user_access_control)

        # Same object reused, table still denied, and no second ee_accesscontrol fetch.
        assert database.user_access_control is user_access_control
        assert "system.notebooks" in database._denied_tables
        ac_queries = [q["sql"] for q in ctx.captured_queries if "ee_accesscontrol" in q["sql"]]
        assert ac_queries == [], ac_queries

    def test_unentitled_org_skips_access_control_fingerprint(self):
        # Without the ACCESS_CONTROL entitlement no user can be restricted, so computing the cache key
        # must not issue the access-control read
        self.organization.available_product_features = []
        self.organization.save()

        runner = self._runner(self.user, base=AnalyticsQueryRunner)
        with CaptureQueriesContext(connection) as ctx:
            runner.get_cache_key()

        ac_queries = [q["sql"] for q in ctx.captured_queries if "ee_accesscontrol" in q["sql"]]
        assert ac_queries == [], ac_queries

        # Entitlement is read off the team's org, so the gate must short-circuit without building
        # user_access_control (whose membership/preload reads are what we're avoiding per query).
        assert runner._user_access_control is None
