from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import WebStatsBreakdown

from posthog.hogql_queries.web_analytics.metrics import (
    WEB_ANALYTICS_QUERY_COUNTER,
    WEB_ANALYTICS_QUERY_DURATION,
    WEB_ANALYTICS_QUERY_ERRORS,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner


def _make_runner(
    query_kind: str = "WebStatsTableQuery",
    breakdown: WebStatsBreakdown | None = WebStatsBreakdown.PAGE,
    conversion_goal: object | None = None,
    sampling: object | None = None,
    properties: list | None = None,
) -> WebAnalyticsQueryRunner:
    """Build a WebAnalyticsQueryRunner with a fake query, team, and date range."""
    query = MagicMock()
    query.kind = query_kind
    query.breakdownBy = breakdown
    query.conversionGoal = conversion_goal
    query.sampling = sampling
    query.properties = properties or []

    team = MagicMock()
    team.pk = 42
    team.organization_id = "org_abc"

    runner = MagicMock(spec=WebAnalyticsQueryRunner)
    runner.query = query
    runner.team = team

    date_range = MagicMock()
    date_range.date_from_str = "2024-01-01"
    date_range.date_to_str = "2024-01-07"
    runner.query_date_range = date_range

    return runner


def _get_counter_value(metric, label_filter: dict) -> float:
    """Get the _total value for a prometheus Counter matching the given labels."""
    for sample in metric.collect()[0].samples:
        if not sample.name.endswith("_total"):
            continue
        if all(sample.labels.get(k) == v for k, v in label_filter.items()):
            return sample.value
    return 0.0


def _get_histogram_count(metric, label_filter: dict) -> float:
    """Get the _count value for a prometheus Histogram matching the given labels."""
    for sample in metric.collect()[0].samples:
        if not sample.name.endswith("_count"):
            continue
        if all(sample.labels.get(k) == v for k, v in label_filter.items()):
            return sample.value
    return 0.0


class TestWebAnalyticsMetrics(TestCase):
    def setUp(self):
        # Clear all prometheus metrics before each test to avoid cross-test leakage
        WEB_ANALYTICS_QUERY_COUNTER._metrics.clear()
        WEB_ANALYTICS_QUERY_DURATION._metrics.clear()
        WEB_ANALYTICS_QUERY_ERRORS._metrics.clear()

    @parameterized.expand(
        [
            (
                "stats_table_page",
                "WebStatsTableQuery",
                WebStatsBreakdown.PAGE,
                None,
                {"query_kind": "WebStatsTableQuery", "breakdown": "Page", "has_conversion_goal": "false"},
            ),
            (
                "overview",
                "WebOverviewQuery",
                None,
                None,
                {"query_kind": "WebOverviewQuery", "breakdown": "none", "has_conversion_goal": "false"},
            ),
            (
                "stats_table_with_conversion",
                "WebStatsTableQuery",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                MagicMock(),
                {
                    "query_kind": "WebStatsTableQuery",
                    "breakdown": "InitialChannelType",
                    "has_conversion_goal": "true",
                },
            ),
            (
                "trends",
                "WebTrendsQuery",
                None,
                None,
                {"query_kind": "WebTrendsQuery", "breakdown": "none", "has_conversion_goal": "false"},
            ),
        ],
    )
    @patch(
        "posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value="user_123"
    )
    def test_successful_query_emits_correct_labels(
        self, _name, query_kind, breakdown, conversion_goal, expected_labels, _mock_tag
    ):
        runner = _make_runner(query_kind=query_kind, breakdown=breakdown, conversion_goal=conversion_goal)

        fake_response = MagicMock()
        fake_response.usedPreAggregatedTables = True

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        label_filter = {**expected_labels, "used_preaggregated": "true"}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, label_filter) == 1.0

    @patch("posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value=None)
    def test_error_query_increments_error_counter(self, _mock_tag):
        runner = _make_runner(query_kind="WebStatsTableQuery", breakdown=WebStatsBreakdown.BROWSER)

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                WebAnalyticsQueryRunner.calculate(runner)

        error_filter = {"query_kind": "WebStatsTableQuery", "breakdown": "Browser", "error_type": "ValueError"}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_ERRORS, error_filter) == 1.0

        counter_filter = {"query_kind": "WebStatsTableQuery", "used_preaggregated": "unknown"}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, counter_filter) == 1.0

    @patch(
        "posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value="user_456"
    )
    def test_canonical_log_line_emitted(self, _mock_tag):
        runner = _make_runner(query_kind="WebOverviewQuery", breakdown=None, properties=["fake_prop"])

        fake_response = MagicMock()
        fake_response.usedPreAggregatedTables = False

        with (
            patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response),
            patch("posthog.hogql_queries.web_analytics.web_analytics_query_runner.logger") as mock_logger,
        ):
            WebAnalyticsQueryRunner.calculate(runner)

        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args
        assert call_kwargs[0][0] == "web_analytics_query"
        kw = call_kwargs[1]
        assert kw["team_id"] == 42
        assert kw["organization_id"] == "org_abc"
        assert kw["user_id"] == "user_456"
        assert kw["query_kind"] == "WebOverviewQuery"
        assert kw["breakdown"] == "none"
        assert kw["used_preaggregated"] == "false"
        assert kw["error"] is False
        assert kw["error_type"] is None
        assert kw["filter_count"] == 1
        assert kw["date_from"] == "2024-01-01"
        assert kw["date_to"] == "2024-01-07"

    @parameterized.expand([(b.name, b) for b in WebStatsBreakdown])
    @patch("posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value=None)
    def test_all_breakdown_values_produce_valid_labels(self, _name, breakdown, _mock_tag):
        runner = _make_runner(breakdown=breakdown)
        fake_response = MagicMock()
        fake_response.usedPreAggregatedTables = None

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        label_filter = {"breakdown": breakdown.value}
        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, label_filter) >= 1.0

    @patch("posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value=None)
    def test_preaggregated_none_maps_to_unknown(self, _mock_tag):
        runner = _make_runner()
        fake_response = MagicMock()
        fake_response.usedPreAggregatedTables = None

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, {"used_preaggregated": "unknown"}) == 1.0

    @patch("posthog.hogql_queries.web_analytics.web_analytics_query_runner.get_query_tag_value", return_value=None)
    def test_response_missing_preaggregated_attr_maps_to_unknown(self, _mock_tag):
        runner = _make_runner()
        fake_response = MagicMock(spec=[])  # empty spec = no attributes

        with patch.object(WebAnalyticsQueryRunner.__mro__[1], "calculate", return_value=fake_response):
            WebAnalyticsQueryRunner.calculate(runner)

        assert _get_counter_value(WEB_ANALYTICS_QUERY_COUNTER, {"used_preaggregated": "unknown"}) == 1.0
