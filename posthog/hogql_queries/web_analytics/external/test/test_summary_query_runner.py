from unittest.mock import patch

from posthog.hogql_queries.web_analytics.external.summary_query_runner import (
    WebAnalyticsExternalSummaryQueryRunner,
    QueryResult,
)
from posthog.schema import (
    WebAnalyticsExternalSummaryQuery,
    DateRange,
)
from posthog.test.base import APIBaseTest
from posthog.hogql.database.s3_table import S3Table


class TestWebAnalyticsExternalSummaryQueryRunner(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.query = WebAnalyticsExternalSummaryQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            properties=[],
        )

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_calculate_success(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = [
            "100,50,200\n",
            "25,50\n",
        ]

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        response = runner.calculate()

        assert response.status == "success"
        assert response.data["unique_visitors"] == 100
        assert response.data["total_sessions"] == 50
        assert response.data["total_pageviews"] == 200
        assert response.data["bounce_rate"] == 0.5  # 25/50
        assert mock_chdb.query.call_count == 2

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_calculate_platform_access_required(self, mock_chdb):
        self.team.organization.is_platform = False
        self.team.organization.save()

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        response = runner.calculate()

        assert response.status == "error"
        assert response.error is not None
        assert response.error.code == "platform_access_required"
        assert mock_chdb.query.call_count == 0

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_calculate_query_execution_failed(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = Exception("chdb connection failed")

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        response = runner.calculate()

        assert response.status == "error"
        assert response.error is not None
        assert response.error.code == "query_execution_failed"

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_calculate_empty_results(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = ["", ""]

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        response = runner.calculate()

        assert response.status == "success"
        assert response.data["unique_visitors"] == 0
        assert response.data["total_sessions"] == 0
        assert response.data["total_pageviews"] == 0
        assert response.data["bounce_rate"] == 0.0

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.chdb")
    def test_bounce_rate_calculation_edge_cases(self, mock_chdb):
        self.team.organization.is_platform = True
        self.team.organization.save()

        mock_chdb.query.side_effect = [
            "100,50,200\n",
            "0,0\n",
        ]

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        response = runner.calculate()

        assert response.data["bounce_rate"] == 0.0

    def test_can_use_s3_tables_property(self):
        self.team.organization.is_platform = True
        self.team.organization.save()

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        assert runner.can_use_s3_tables is True

        self.team.organization.is_platform = False
        self.team.organization.save()

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)
        assert runner.can_use_s3_tables is False

    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.build_function_call")
    def test_build_s3_table_functions(self, mock_build_function_call):
        mock_build_function_call.return_value = "s3('url', 'format', 'structure')"

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

        stats_func = runner._build_s3_stats_table_func()
        bounces_func = runner._build_s3_bounces_table_func()

        assert stats_func == "s3('url', 'format', 'structure')"
        assert bounces_func == "s3('url', 'format', 'structure')"
        assert mock_build_function_call.call_count == 2

    def test_process_query_results_with_string_conversion(self):
        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

        stats_result = QueryResult(rows=[("100", "50", "200")])
        bounces_result = QueryResult(rows=[("25", "50")])

        results = runner._process_query_results(stats_result, bounces_result)

        assert results["unique_visitors"] == 100
        assert results["total_sessions"] == 50
        assert results["total_pageviews"] == 200
        assert results["bounce_rate"] == 0.5

    def test_process_query_results_with_empty_strings(self):
        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

        stats_result = QueryResult(rows=[("", "0", "")])
        bounces_result = QueryResult(rows=[("", "0")])

        results = runner._process_query_results(stats_result, bounces_result)

        assert results["unique_visitors"] == 0
        assert results["total_sessions"] == 0
        assert results["total_pageviews"] == 0
        assert results["bounce_rate"] == 0.0

    def test_build_correct_paths_and_structures_production(self):
        """Test that correct paths and structures are built for chdb queries in production environment"""
        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", False):
            runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

            # Test stats table function - should use IAM role (no credentials) in production
            stats_func = runner._build_s3_stats_table_func()

            # Should include the basic S3 function structure
            assert stats_func.startswith("s3('https://")
            assert "'Native'" in stats_func
            assert "period_bucket DateTime" in stats_func
            assert "persons_uniq_state AggregateFunction(uniq, UUID)" in stats_func

            # Should NOT include any credentials (access keys/secrets)
            # In production, the pattern should be: s3('url', 'format', 'structure')
            # If credentials were included, they would appear between URL and format
            url_end = stats_func.find("data.native'")
            format_start = stats_func.find("'Native'")
            between_url_and_format = stats_func[url_end + len("data.native'") : format_start]
            assert (
                between_url_and_format.strip() == ","
            ), f"Expected only comma between URL and format, found: {between_url_and_format}"

            # Test bounces table function - should use IAM role (no credentials) in production
            bounces_func = runner._build_s3_bounces_table_func()
            assert bounces_func.startswith("s3('https://")
            assert "'Native'" in bounces_func
            assert "bounces_count_state AggregateFunction(sum, UInt64)" in bounces_func

            # Should NOT include any credentials for bounces either
            url_end = bounces_func.find("data.native'")
            format_start = bounces_func.find("'Native'")
            between_url_and_format = bounces_func[url_end + len("data.native'") : format_start]
            assert (
                between_url_and_format.strip() == ","
            ), f"Expected only comma between URL and format, found: {between_url_and_format}"

    @patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", True)
    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.create_s3_web_stats_table")
    @patch("posthog.hogql_queries.web_analytics.external.summary_query_runner.create_s3_web_bounces_table")
    def test_build_correct_paths_and_structures_debug(self, mock_create_bounces_table, mock_create_stats_table):
        mock_stats_table = S3Table(
            name="web_stats_daily_s3",
            url=f"http://objectstorage:19000/posthog/web_stats_daily_export/{self.team.pk}/data.native",
            format="Native",
            access_key="test_key",
            access_secret="test_secret",
            structure="period_bucket DateTime, team_id UInt64, persons_uniq_state AggregateFunction(uniq, UUID), sessions_uniq_state AggregateFunction(uniq, String), pageviews_count_state AggregateFunction(sum, UInt64)",
            fields={},
        )

        mock_bounces_table = S3Table(
            name="web_bounces_daily_s3",
            url=f"http://objectstorage:19000/posthog/web_bounces_daily_export/{self.team.pk}/data.native",
            format="Native",
            access_key="test_key",
            access_secret="test_secret",
            structure="period_bucket DateTime, team_id UInt64, persons_uniq_state AggregateFunction(uniq, UUID), sessions_uniq_state AggregateFunction(uniq, String), pageviews_count_state AggregateFunction(sum, UInt64), bounces_count_state AggregateFunction(sum, UInt64), total_session_duration_state AggregateFunction(sum, UInt64)",
            fields={},
        )

        mock_create_stats_table.return_value = mock_stats_table
        mock_create_bounces_table.return_value = mock_bounces_table

        runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

        stats_func = runner._build_s3_stats_table_func()
        expected_stats = f"s3('http://objectstorage:19000/posthog/web_stats_daily_export/{self.team.pk}/data.native', 'test_key', 'test_secret', 'Native', 'period_bucket DateTime, team_id UInt64, persons_uniq_state AggregateFunction(uniq, UUID), sessions_uniq_state AggregateFunction(uniq, String), pageviews_count_state AggregateFunction(sum, UInt64)')"
        assert stats_func == expected_stats

        bounces_func = runner._build_s3_bounces_table_func()
        expected_bounces = f"s3('http://objectstorage:19000/posthog/web_bounces_daily_export/{self.team.pk}/data.native', 'test_key', 'test_secret', 'Native', 'period_bucket DateTime, team_id UInt64, persons_uniq_state AggregateFunction(uniq, UUID), sessions_uniq_state AggregateFunction(uniq, String), pageviews_count_state AggregateFunction(sum, UInt64), bounces_count_state AggregateFunction(sum, UInt64), total_session_duration_state AggregateFunction(sum, UInt64)')"
        assert bounces_func == expected_bounces
