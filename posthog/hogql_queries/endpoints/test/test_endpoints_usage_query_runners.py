from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EndpointsUsageBreakdown,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
    IntervalType,
    MaterializationType,
)

from posthog.hogql.printer import to_printed_hogql

from posthog.hogql_queries.endpoints.endpoints_usage_overview import EndpointsUsageOverviewQueryRunner
from posthog.hogql_queries.endpoints.endpoints_usage_query_runner import safe_float
from posthog.hogql_queries.endpoints.endpoints_usage_table import EndpointsUsageTableQueryRunner
from posthog.hogql_queries.endpoints.endpoints_usage_trends import EndpointsUsageTrendsQueryRunner


class TestSafeFloat(APIBaseTest):
    @parameterized.expand(
        [
            (None, 0.0),
            (0, 0.0),
            (1, 1.0),
            (1.5, 1.5),
            ("1.5", 1.5),
            ("invalid", 0.0),
            ([], 0.0),
            ({}, 0.0),
            (float("inf"), float("inf")),
        ]
    )
    def test_safe_float_conversions(self, input_val, expected):
        result = safe_float(input_val)
        self.assertEqual(result, expected)


class TestEndpointsUsageOverviewQueryRunner(ClickhouseTestMixin, QueryMatchingTest, APIBaseTest):
    @freeze_time("2024-01-15T12:00:00Z")
    def test_overview_query_sql(self):
        query = EndpointsUsageOverviewQuery(
            kind="EndpointsUsageOverviewQuery",
            dateRange=DateRange(date_from="-7d"),
        )
        runner = EndpointsUsageOverviewQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_overview_query_with_endpoint_filter_sql(self):
        query = EndpointsUsageOverviewQuery(
            kind="EndpointsUsageOverviewQuery",
            dateRange=DateRange(date_from="-7d"),
            endpointNames=["my-endpoint"],
        )
        runner = EndpointsUsageOverviewQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_overview_query_with_materialization_filter_sql(self):
        query = EndpointsUsageOverviewQuery(
            kind="EndpointsUsageOverviewQuery",
            dateRange=DateRange(date_from="-7d"),
            materializationType=MaterializationType.MATERIALIZED,
        )
        runner = EndpointsUsageOverviewQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_row_to_metrics_dict(self):
        query = EndpointsUsageOverviewQuery(
            kind="EndpointsUsageOverviewQuery",
            dateRange=DateRange(date_from="-7d"),
        )
        runner = EndpointsUsageOverviewQueryRunner(query=query, team=self.team)

        row = [100, 5000, 1.5, 50.0, 95.0, 0.05, 60, 40]
        result = runner._row_to_metrics_dict(row)

        assert result == {
            "total_requests": 100.0,
            "total_bytes_read": 5000.0,
            "total_cpu_seconds": 1.5,
            "avg_query_duration_ms": 50.0,
            "p95_query_duration_ms": 95.0,
            "error_rate": 0.05,
            "materialized_requests": 60.0,
            "inline_requests": 40.0,
        }

    @parameterized.expand(
        [
            (100.0, 50.0, 100.0),
            (50.0, 100.0, -50.0),
            (100.0, 0.0, 100.0),
            (0.0, 100.0, -100.0),
            (0.0, 0.0, 0.0),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_calculate_change_pct(self, current, previous, expected):
        query = EndpointsUsageOverviewQuery(
            kind="EndpointsUsageOverviewQuery",
            dateRange=DateRange(date_from="-7d"),
        )
        runner = EndpointsUsageOverviewQueryRunner(query=query, team=self.team)

        result = runner._calculate_change_pct(current, previous)

        assert result == expected


class TestEndpointsUsageTrendsQueryRunner(ClickhouseTestMixin, QueryMatchingTest, APIBaseTest):
    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_requests_metric_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="requests",
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_bytes_read_metric_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="bytes_read",
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_cpu_seconds_metric_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="cpu_seconds",
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_error_rate_metric_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="error_rate",
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_hourly_interval_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="requests",
            interval=IntervalType.HOUR,
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_weekly_interval_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-30d"),
            metric="requests",
            interval=IntervalType.WEEK,
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_with_endpoint_breakdown_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="requests",
            breakdownBy=EndpointsUsageBreakdown.ENDPOINT,
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_with_materialization_breakdown_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="requests",
            breakdownBy=EndpointsUsageBreakdown.MATERIALIZATION_TYPE,
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_trends_query_with_status_breakdown_sql(self):
        query = EndpointsUsageTrendsQuery(
            kind="EndpointsUsageTrendsQuery",
            dateRange=DateRange(date_from="-7d"),
            metric="requests",
            breakdownBy=EndpointsUsageBreakdown.STATUS,
        )
        runner = EndpointsUsageTrendsQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)


class TestEndpointsUsageTableQueryRunner(ClickhouseTestMixin, QueryMatchingTest, APIBaseTest):
    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_by_endpoint_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.ENDPOINT,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_by_materialization_type_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.MATERIALIZATION_TYPE,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_by_api_key_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.API_KEY,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_by_status_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.STATUS,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_with_pagination_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.ENDPOINT,
            limit=50,
            offset=25,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_with_order_by_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.ENDPOINT,
            orderBy=["bytes_read", "ASC"],
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_table_query_with_materialization_filter_sql(self):
        query = EndpointsUsageTableQuery(
            kind="EndpointsUsageTableQuery",
            dateRange=DateRange(date_from="-7d"),
            breakdownBy=EndpointsUsageBreakdown.ENDPOINT,
            materializationType=MaterializationType.INLINE,
        )
        runner = EndpointsUsageTableQueryRunner(query=query, team=self.team)

        hogql = to_printed_hogql(runner.to_query(), self.team)

        self.assertQueryMatchesSnapshot(hogql)
