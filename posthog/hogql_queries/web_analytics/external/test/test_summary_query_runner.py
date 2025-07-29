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
from posthog.hogql.database.schema.web_analytics_s3 import (
    _get_s3_credentials,
    create_s3_web_stats_table,
    create_s3_web_bounces_table,
)


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

    def test_build_correct_paths_and_structures_for_s3_chdb_queries_in_production_mode(self):
        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", False):
            runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

            stats_func = runner._build_s3_stats_table_func()
            bounces_func = runner._build_s3_bounces_table_func()

            # The generated functions should be valid S3 function calls
            assert stats_func.startswith("s3(")
            assert "'Native'" in stats_func
            assert bounces_func.startswith("s3(")
            assert "'Native'" in bounces_func

            # Most importantly, verify that the create functions actually return tables with no credentials
            stats_table = create_s3_web_stats_table(self.team.pk)
            assert stats_table.access_key is None, "Production should use IAM roles (no access key)"
            assert stats_table.access_secret is None, "Production should use IAM roles (no secret key)"
            assert stats_table.format == "Native"
            assert "web_stats_daily_export" in stats_table.url

            bounces_table = create_s3_web_bounces_table(self.team.pk)
            assert bounces_table.access_key is None, "Production should use IAM roles (no access key)"
            assert bounces_table.access_secret is None, "Production should use IAM roles (no secret key)"
            assert bounces_table.format == "Native"
            assert "web_bounces_daily_export" in bounces_table.url

    def test_build_correct_paths_and_structures_for_s3_chdb_queries_in_debug_mode(self):
        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", True):
            runner = WebAnalyticsExternalSummaryQueryRunner(query=self.query, team=self.team)

            # Test that the S3 table creation functions work correctly in debug mode
            stats_func = runner._build_s3_stats_table_func()
            bounces_func = runner._build_s3_bounces_table_func()

            # The generated functions should be valid S3 function calls
            assert stats_func.startswith("s3(")
            assert "'Native'" in stats_func
            assert bounces_func.startswith("s3(")
            assert "'Native'" in bounces_func

            # Most importantly, verify that the create functions return tables WITH credentials in debug
            from posthog.hogql.database.schema.web_analytics_s3 import (
                create_s3_web_stats_table,
                create_s3_web_bounces_table,
            )

            stats_table = create_s3_web_stats_table(self.team.pk)
            assert stats_table.access_key is not None
            assert stats_table.access_secret is not None
            assert stats_table.format == "Native"
            assert "web_stats_daily_export" in stats_table.url

            bounces_table = create_s3_web_bounces_table(self.team.pk)
            assert bounces_table.access_key is not None
            assert bounces_table.access_secret is not None
            assert bounces_table.format == "Native"
            assert "web_bounces_daily_export" in bounces_table.url

    def test_credential_helper_function_behavior(self):
        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", False):
            access_key, access_secret = _get_s3_credentials()
            assert access_key is None
            assert access_secret is None

        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", True):
            with patch("posthog.hogql.database.schema.web_analytics_s3.OBJECT_STORAGE_ACCESS_KEY_ID", "debug_key"):
                with patch(
                    "posthog.hogql.database.schema.web_analytics_s3.OBJECT_STORAGE_SECRET_ACCESS_KEY", "debug_secret"
                ):
                    access_key, access_secret = _get_s3_credentials()
                    assert access_key == "debug_key"
                    assert access_secret == "debug_secret"

    def test_s3_table_creation_integration(self):
        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", False):
            stats_table = create_s3_web_stats_table(self.team.pk)
            assert stats_table.access_key is None
            assert stats_table.access_secret is None
            assert stats_table.format == "Native"
            assert stats_table.name == "web_stats_daily_s3"
            assert "web_stats_daily_export" in stats_table.url
            assert str(self.team.pk) in stats_table.url

            bounces_table = create_s3_web_bounces_table(self.team.pk)
            assert bounces_table.access_key is None
            assert bounces_table.access_secret is None
            assert bounces_table.format == "Native"
            assert bounces_table.name == "web_bounces_daily_s3"
            assert "web_bounces_daily_export" in bounces_table.url

        with patch("posthog.hogql.database.schema.web_analytics_s3.DEBUG", True):
            stats_table = create_s3_web_stats_table(self.team.pk)
            assert stats_table.access_key is not None
            assert stats_table.access_secret is not None
            assert stats_table.format == "Native"
            assert stats_table.name == "web_stats_daily_s3"

            bounces_table = create_s3_web_bounces_table(self.team.pk)
            assert bounces_table.access_key is not None
            assert bounces_table.access_secret is not None
            assert bounces_table.format == "Native"
            assert bounces_table.name == "web_bounces_daily_s3"
