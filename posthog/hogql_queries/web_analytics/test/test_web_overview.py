from typing import Optional
from unittest.mock import MagicMock, patch

import sqlparse
from freezegun import freeze_time
from contextlib import contextmanager

from posthog.clickhouse.client.connection import get_client_from_pool

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models import Action, Element, Cohort
from posthog.warehouse.models import (
    DataWarehouseTable,
    DataWarehouseCredential,
)
from posthog.models.utils import uuid7
from posthog.schema import (
    CompareFilter,
    CurrencyCode,
    WebOverviewQuery,
    DateRange,
    SessionTableVersion,
    HogQLQueryModifiers,
    CustomEventConversionGoal,
    ActionConversionGoal,
    BounceRatePageViewMode,
    WebOverviewQueryResponse,
    RevenueTrackingConfig,
    RevenueCurrencyPropertyConfig,
    RevenueTrackingEventItem,
    RevenueTrackingDataWarehouseTable,
)
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)


@snapshot_clickhouse_queries
class TestWebOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                lcp_score = None
                revenue = None
                currency = None
                if event == "$pageview":
                    url = extra[0] if extra else None
                elif event == "$autocapture":
                    elements = extra[0] if extra else None
                elif event == "$web_vitals":
                    lcp_score = extra[0] if extra else None
                elif event.startswith("purchase"):
                    revenue = extra[0] if extra else None
                    currency = extra[1] if extra and len(extra) > 1 and extra[1] else None
                properties = extra[1] if extra and len(extra) > 1 and isinstance(extra[1], dict) else {}

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$current_url": url,
                        "$web_vitals_LCP_value": lcp_score,
                        "revenue": revenue,
                        "currency": currency,
                        **properties,
                    },
                    elements=elements,
                )
        return person_result

    def _create_data_warehouse_table(self, name: str, revenue_column: str, timestamp_column: str, currency_column: str):
        return DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,  # Parquet is commonly used in other tests
            team=self.team,
            credential=DataWarehouseCredential.objects.create(
                team=self.team,
                access_key="test-key",
                access_secret="test-secret",
            ),
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                revenue_column: {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                timestamp_column: {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
                currency_column: {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
            },
        )

    def _run_web_overview_query(
        self,
        date_from: str,
        date_to: str,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        compare: bool = True,
        limit_context: Optional[LimitContext] = None,
        filter_test_accounts: Optional[bool] = False,
        action: Optional[Action] = None,
        custom_event: Optional[str] = None,
        bounce_rate_mode: Optional[BounceRatePageViewMode] = BounceRatePageViewMode.COUNT_PAGEVIEWS,
        include_revenue: Optional[bool] = False,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(
                sessionTableVersion=session_table_version, bounceRatePageViewMode=bounce_rate_mode
            )
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],
                compareFilter=CompareFilter(compare=compare) if compare else None,
                modifiers=modifiers,
                filterTestAccounts=filter_test_accounts,
                includeRevenue=include_revenue,
                conversionGoal=ActionConversionGoal(actionId=action.id)
                if action
                else CustomEventConversionGoal(customEventName=custom_event)
                if custom_event
                else None,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query, limit_context=limit_context)
            response = runner.calculate()
            WebOverviewQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        results = self._run_web_overview_query(
            "2023-12-08",
            "2023-12-15",
        ).results
        assert [item.key for item in results] == [
            "visitors",
            "views",
            "sessions",
            "session duration",
            "bounce rate",
        ]

        results = self._run_web_overview_query("2023-12-08", "2023-12-15").results
        assert [item.key for item in results] == [
            "visitors",
            "views",
            "sessions",
            "session duration",
            "bounce rate",
        ]

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/foo",
                    "url_matching": "regex",
                }
            ],
        )
        results = self._run_web_overview_query("2023-12-08", "2023-12-15", action=action).results

        assert [item.key for item in results] == [
            "visitors",
            "total conversions",
            "unique conversions",
            "conversion rate",
        ]

    def test_increase_in_users(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-12"))
        s2 = str(uuid7("2023-12-11"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1a), ("2023-12-03", s1a), ("2023-12-12", s1b)]),
                ("p2", [("2023-12-11", s2)]),
            ]
        )

        results = self._run_web_overview_query(
            "2023-12-08",
            "2023-12-15",
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(1, visitors.previous)
        self.assertEqual(100, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(2, views.value)
        self.assertEqual(2, views.previous)
        self.assertEqual(0, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(2, sessions.value)
        self.assertEqual(1, sessions.previous)
        self.assertEqual(100, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(0, duration_s.value)
        self.assertEqual(60 * 60 * 24, duration_s.previous)
        self.assertEqual(-100, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(100, bounce.value)
        self.assertEqual(0, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    def test_increase_in_users_using_mobile(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-12"))
        s2 = str(uuid7("2023-12-11"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1a), ("2023-12-03", s1a), ("2023-12-12", s1b)]),
                ("p2", [("2023-12-11", s2)]),
            ],
            event="$screen",
        )

        results = self._run_web_overview_query(
            "2023-12-08",
            "2023-12-15",
            bounce_rate_mode=BounceRatePageViewMode.UNIQ_PAGE_SCREEN_AUTOCAPTURES,  # bounce rate won't work in the other modes
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(1, visitors.previous)
        self.assertEqual(100, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(2, views.value)
        self.assertEqual(2, views.previous)
        self.assertEqual(0, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(2, sessions.value)
        self.assertEqual(1, sessions.previous)
        self.assertEqual(100, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(0, duration_s.value)
        self.assertEqual(60 * 60 * 24, duration_s.previous)
        self.assertEqual(-100, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(100, bounce.value)
        self.assertEqual(0, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    def test_all_time(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-12"))
        s2 = str(uuid7("2023-12-11"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a), ("2023-12-03", s1a), ("2023-12-12", s1b)]),
                ("p2", [("2023-12-11", s2)]),
            ]
        )

        results = self._run_web_overview_query(
            "all",
            "2023-12-15",
            compare=False,
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(None, visitors.previous)
        self.assertEqual(None, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(4, views.value)
        self.assertEqual(None, views.previous)
        self.assertEqual(None, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(3, sessions.value)
        self.assertEqual(None, sessions.previous)
        self.assertEqual(None, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(60 * 60 * 24 / 3, duration_s.value)
        self.assertEqual(None, duration_s.previous)
        self.assertEqual(None, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertAlmostEqual(100 * 2 / 3, bounce.value)
        self.assertEqual(None, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    def test_comparison(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-12"))
        s2 = str(uuid7("2023-12-11"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a), ("2023-12-03", s1a), ("2023-12-12", s1b)]),
                ("p2", [("2023-12-11", s2)]),
            ]
        )

        results = self._run_web_overview_query(
            "2023-12-06",
            "2023-12-13",
            compare=True,
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(1, visitors.previous)
        self.assertEqual(100, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(2, views.value)
        self.assertEqual(2, views.previous)
        self.assertEqual(0, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(2, sessions.value)
        self.assertEqual(1, sessions.previous)
        self.assertEqual(100, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(0, duration_s.value)
        self.assertEqual(60 * 60 * 24, duration_s.previous)
        self.assertEqual(-100, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertAlmostEqual(100, bounce.value)
        self.assertEqual(0, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    def test_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1), ("2023-12-03", s1)])])

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", filter_test_accounts=True).results

        visitors = results[0]
        self.assertEqual(0, visitors.value)

        views = results[1]
        self.assertEqual(0, views.value)

        sessions = results[2]
        self.assertEqual(0, sessions.value)

        duration_s = results[3]
        self.assertEqual(None, duration_s.value)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(None, bounce.value)

    def test_filter_cohort(self):
        cohort = Cohort.objects.create(team=self.team, name="test")
        self.team.test_account_filters = [
            {
                "key": "id",
                "value": cohort.id,
                "type": "cohort",
            },
        ]
        self.team.save()
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1), ("2023-12-03", s1)])])

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", filter_test_accounts=True).results

        visitors = results[0]
        self.assertEqual(0, visitors.value)

        views = results[1]
        self.assertEqual(0, views.value)

        sessions = results[2]
        self.assertEqual(0, sessions.value)

        duration_s = results[3]
        self.assertEqual(None, duration_s.value)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(None, bounce.value)

    def test_dont_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1), ("2023-12-03", s1)])])

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", filter_test_accounts=False).results

        visitors = results[0]
        self.assertEqual(1, visitors.value)

    def test_correctly_counts_pageviews_in_long_running_session(self):
        # this test is important when using the v1 sessions table as the raw sessions table will have 3 entries, one per day
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1), ("2023-12-02", s1), ("2023-12-03", s1)]),
            ]
        )

        results = self._run_web_overview_query(
            "2023-12-01",
            "2023-12-03",
        ).results

        visitors = results[0]
        self.assertEqual(1, visitors.value)

        views = results[1]
        self.assertEqual(3, views.value)

        sessions = results[2]
        self.assertEqual(1, sessions.value)

    def test_conversion_goal_no_conversions(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/bar",
                    "url_matching": "regex",
                }
            ],
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action).results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 0

        unique_conversions = results[2]
        assert unique_conversions.value == 0

        conversion_rate = results[3]
        assert conversion_rate.value == 0

    def test_conversion_goal_one_pageview_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/foo",
                    "url_matching": "regex",
                }
            ],
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action).results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 1

        unique_conversions = results[2]
        assert unique_conversions.value == 1

        conversion_rate = results[3]
        assert conversion_rate.value == 100

    def test_conversion_goal_one_custom_event_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ],
            event="custom_event",
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", custom_event="custom_event").results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 1

        unique_conversions = results[2]
        assert unique_conversions.value == 1

        conversion_rate = results[3]
        assert conversion_rate.value == 100

    def test_conversion_goal_one_custom_action_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1)]),
            ],
            event="custom_event",
        )

        action = Action.objects.create(
            team=self.team,
            name="Did Custom Event",
            steps_json=[
                {
                    "event": "custom_event",
                }
            ],
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action).results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 1

        unique_conversions = results[2]
        assert unique_conversions.value == 1

        conversion_rate = results[3]
        assert conversion_rate.value == 100

    def test_conversion_goal_one_autocapture_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, [Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")])]),
            ],
            event="$autocapture",
        )

        action = Action.objects.create(
            team=self.team,
            name="Paid $10",
            steps_json=[
                {
                    "event": "$autocapture",
                    "tag_name": "button",
                    "text": "Pay $10",
                }
            ],
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action).results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 1

        unique_conversions = results[2]
        assert unique_conversions.value == 1

        conversion_rate = results[3]
        assert conversion_rate.value == 100

    def test_conversion_rate(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-01", s1, "https://www.example.com/foo"),
                        ("2023-12-01", s1, "https://www.example.com/foo"),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-01", s2, "https://www.example.com/foo"),
                        ("2023-12-01", s2, "https://www.example.com/bar"),
                    ],
                ),
                ("p3", [("2023-12-01", s3, "https://www.example.com/bar")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/foo",
                    "url_matching": "regex",
                }
            ],
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action).results

        visitors = results[0]
        assert visitors.value == 3

        conversion = results[1]
        assert conversion.value == 3

        unique_conversions = results[2]
        assert unique_conversions.value == 2

        conversion_rate = results[3]
        self.assertAlmostEqual(conversion_rate.value, 100 * 2 / 3)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_revenue(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))

        self.team.revenue_tracking_config = RevenueTrackingConfig(
            baseCurrency=CurrencyCode.GBP,
            events=[
                RevenueTrackingEventItem(
                    eventName="purchase",
                    revenueProperty="revenue",
                    revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency"),
                )
            ],
        ).model_dump()
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100, "BRL")]),
            ],
            event="purchase",
        )
        response = self._run_web_overview_query("2023-12-01", "2023-12-03", include_revenue=True)
        results = response.results

        visitors = results[0]
        assert visitors.value == 1

        views = results[1]
        assert views.value == 0

        sessions = results[2]
        assert sessions.value == 1

        duration = results[3]
        assert duration.value == 0

        bounce = results[4]
        assert bounce.value is None

        revenue = results[5]
        assert revenue.kind == "currency"
        assert revenue.value == 16.0763662979

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_revenue_without_feature_flag(self, feature_enabled_mock):
        s1 = str(uuid7("2023-12-02"))

        self.team.revenue_tracking_config = {
            "events": [
                {
                    "eventName": "purchase",
                    "revenueProperty": "revenue",
                    "revenueCurrencyProperty": {"property": "currency"},
                }
            ],
            "baseCurrency": CurrencyCode.GBP,
        }
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100, "BRL")]),
            ],
            event="purchase",
        )
        results = self._run_web_overview_query("2023-12-01", "2023-12-03", include_revenue=True).results

        visitors = results[0]
        assert visitors.value == 1

        views = results[1]
        assert views.value == 0

        sessions = results[2]
        assert sessions.value == 1

        duration = results[3]
        assert duration.value == 0

        bounce = results[4]
        assert bounce.value is None

        revenue = results[5]
        assert revenue.kind == "currency"
        assert revenue.value == 100

    def test_revenue_multiple_events(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-02"))

        self.team.revenue_tracking_config = {
            "events": [
                {"eventName": "purchase1", "revenueProperty": "revenue"},
                {"eventName": "purchase2", "revenueProperty": "revenue"},
            ]
        }
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase1",
        )
        self._create_events(
            [
                ("p2", [("2023-12-02", s2, 50)]),
            ],
            event="purchase2",
        )
        results = self._run_web_overview_query("2023-12-01", "2023-12-03", include_revenue=True).results

        visitors = results[0]
        assert visitors.value == 2

        views = results[1]
        assert views.value == 0

        sessions = results[2]
        assert sessions.value == 2

        duration = results[3]
        assert duration.value == 0

        bounce = results[4]
        assert bounce.value is None

        revenue = results[5]
        assert revenue.kind == "currency"
        assert revenue.value == 150

    def test_revenue_no_config(self):
        s1 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase",
        )
        results = self._run_web_overview_query("2023-12-01", "2023-12-03", include_revenue=True).results

        revenue = results[5]
        assert revenue.kind == "currency"
        assert revenue.value is None

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_revenue_with_data_warehouse_table(self, feature_enabled_mock):
        # Because we're mocking the `clichhouse_driver.Client.execute` method,
        # we need to track the queries that are being executed because
        # the original `snapshot_clickhouse_queries` decorator won't run anymore
        queries = []

        # Spy on the `clichhouse_driver.Client.execute` method. This is a bit of
        # a roundabout way to handle this, but it seems tricky to spy on the
        # unbound class method `Client.execute` directly easily
        @contextmanager
        def get_client(orig_fn, *args, **kwargs):
            with orig_fn(*args, **kwargs) as client:
                original_client_execute = client.execute

                def execute_wrapper(query, *args, **kwargs):
                    if (
                        sqlparse.format(query, strip_comments=True)
                        .strip()
                        .startswith(("SELECT", "WITH", "select", "with"))
                    ):
                        queries.append(query)

                    if "database_with_revenue_column" in query:
                        return (
                            [
                                [
                                    0,
                                    0,  # Visitors
                                    0,
                                    0,  # Views
                                    0,
                                    0,  # Sessions
                                    0,
                                    0,  # Duration
                                    0,
                                    0,  # Bounce
                                    0,
                                    0,  # Revenue
                                ]
                            ],
                            [],
                        )

                    return original_client_execute(query, *args, **kwargs)

                with patch.object(client, "execute", wraps=execute_wrapper) as _:
                    yield client

        # Once we leave `with`, the patch is no longer active
        with get_client_from_pool._temp_patch(get_client) as _:
            # Create two different data warehouse tables to guarantee they're both added to the query
            self._create_data_warehouse_table(
                "database_with_revenue_column_1", "revenue_1", "timestamp_1", "currency_1"
            )
            self._create_data_warehouse_table(
                "database_with_revenue_column_2", "revenue_2", "timestamp_2", "currency_2"
            )

            self.team.revenue_tracking_config = RevenueTrackingConfig(
                baseCurrency=CurrencyCode.GBP,
                events=[
                    RevenueTrackingEventItem(
                        eventName="purchase",
                        revenueProperty="revenue",
                        revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency"),
                    )
                ],
                dataWarehouseTables=[
                    RevenueTrackingDataWarehouseTable(
                        tableName="database_with_revenue_column_1",
                        revenueColumn="revenue_1",
                        timestampColumn="timestamp_1",
                        revenueCurrencyColumn=RevenueCurrencyPropertyConfig(property="currency_1"),
                    ),
                    RevenueTrackingDataWarehouseTable(
                        tableName="database_with_revenue_column_2",
                        revenueColumn="revenue_2",
                        timestampColumn="timestamp_2",
                        revenueCurrencyColumn=RevenueCurrencyPropertyConfig(static=CurrencyCode.EUR),
                    ),
                ],
            ).model_dump()
            self.team.save()

            self._create_events(
                [
                    ("p1", [("2023-12-02", str(uuid7("2023-12-02")), 100, "BRL")]),
                ],
                event="purchase",
            )

            # Run this, but don't assert on the output because we're mocking it above
            self._run_web_overview_query("2023-12-01", "2023-12-03", include_revenue=True)

            # Rather assert on the queries that were executed
            for query in queries:
                if "FROM system.columns" not in query:
                    self.assertQueryMatchesSnapshot(query)

    def test_revenue_conversion_event(self):
        s1 = str(uuid7("2023-12-02"))

        self.team.revenue_tracking_config = {"events": [{"eventName": "purchase", "revenueProperty": "revenue"}]}
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase",
        )
        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", include_revenue=True, custom_event="purchase"
        ).results

        visitors = results[0]
        assert visitors.value == 1

        conversion = results[1]
        assert conversion.value == 1

        unique_conversions = results[2]
        assert unique_conversions.value == 1

        conversion_rate = results[3]
        assert conversion_rate.value == 100

        revenue = results[4]
        assert revenue.kind == "currency"
        assert revenue.value == 100

    def test_revenue_conversion_event_with_multiple_revenue_events(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-02"))

        self.team.revenue_tracking_config = {
            "events": [
                {"eventName": "purchase1", "revenueProperty": "revenue"},
                {"eventName": "purchase2", "revenueProperty": "revenue"},
            ]
        }
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase1",
        )
        self._create_events(
            [
                ("p2", [("2023-12-02", s2, 50)]),
            ],
            event="purchase2",
        )
        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", include_revenue=True, custom_event="purchase1"
        ).results

        revenue = results[4]
        assert revenue.kind == "currency"
        assert revenue.value == 100

    def test_revenue_conversion_no_config(self):
        s1 = str(uuid7("2023-12-02"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase",
        )
        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", include_revenue=True, custom_event="purchase"
        ).results

        revenue = results[4]
        assert revenue.kind == "currency"
        assert revenue.value is None

    def test_no_revenue_when_event_conversion_goal_set_but_include_revenue_disabled(self):
        s1 = str(uuid7("2023-12-01"))

        self.team.revenue_tracking_config = {"events": [{"eventName": "purchase", "revenueProperty": "revenue"}]}
        self.team.save()

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="purchase",
        )

        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", custom_event="purchase", include_revenue=False
        ).results

        assert len(results) == 4

    def test_no_revenue_when_action_conversion_goal_set_but_include_revenue_disabled(self):
        s1 = str(uuid7("2023-12-01"))

        self.team.revenue_tracking_config = {"events": [{"eventName": "purchase", "revenueProperty": "revenue"}]}
        self.team.save()

        action = Action.objects.create(
            team=self.team,
            name="Did Custom Event",
            steps_json=[
                {
                    "event": "custom_event",
                }
            ],
        )

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, 100)]),
            ],
            event="custom_event",
        )

        results = self._run_web_overview_query("2023-12-01", "2023-12-03", action=action, include_revenue=False).results

        assert len(results) == 4

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_limit_is_context_aware(self, mock_sync_execute: MagicMock):
        self._run_web_overview_query("2023-12-01", "2023-12-03", limit_context=LimitContext.QUERY_ASYNC)

        mock_sync_execute.assert_called_once()
        self.assertIn(f" max_execution_time={HOGQL_INCREASED_MAX_EXECUTION_TIME},", mock_sync_execute.call_args[0][0])
