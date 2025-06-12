from typing import Any
import csv
from io import StringIO
import structlog
import chdb
from posthog.hogql import ast
from posthog.hogql.database.s3_table import build_function_call
from posthog.hogql.database.schema.web_analytics_s3 import (
    create_s3_web_stats_table,
    create_s3_web_bounces_table,
)
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    ExternalQueryError,
    WebAnalyticsExternalSummaryQuery,
    WebAnalyticsExternalSummaryQueryResponse,
)

logger = structlog.get_logger(__name__)


class WebAnalyticsExternalSummaryQueryRunner(WebAnalyticsQueryRunner):
    query: WebAnalyticsExternalSummaryQuery
    response: WebAnalyticsExternalSummaryQueryResponse

    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def calculate(self) -> WebAnalyticsExternalSummaryQueryResponse:
        if not self.can_use_s3_tables:
            return WebAnalyticsExternalSummaryQueryResponse(
                data={},
                error=ExternalQueryError(
                    code="platform_access_required",
                    detail="Organization must have platform access to use external web analytics",
                ),
                dateRange=self.query.dateRange,
                status="error",
            )

        try:
            stats_result = self._execute_stats_query()
            bounces_result = self._execute_bounces_query()

            results = self._process_query_results(stats_result, bounces_result)

            return WebAnalyticsExternalSummaryQueryResponse(
                data={
                    "unique_visitors": results["unique_visitors"],
                    "total_sessions": results["total_sessions"],
                    "total_pageviews": results["total_pageviews"],
                    "bounce_rate": results["bounce_rate"],
                },
                dateRange=self.query.dateRange,
                status="success",
            )

        except Exception as e:
            logger.error("Platform web analytics query failed", team_id=self.team.pk, error=str(e), exc_info=True)
            return WebAnalyticsExternalSummaryQueryResponse(
                data={},
                error=ExternalQueryError(
                    code="query_execution_failed",
                    detail="Failed to execute query",
                ),
                dateRange=self.query.dateRange,
                status="error",
            )

    @cached_property
    def can_use_s3_tables(self) -> bool:
        return self.team.organization.is_platform

    def _build_s3_stats_table_func(self) -> str:
        web_stats_table = create_s3_web_stats_table(self.team.pk)
        return build_function_call(
            url=web_stats_table.url,
            format=web_stats_table.format,
            access_key=web_stats_table.access_key,
            access_secret=web_stats_table.access_secret,
            structure=web_stats_table.structure,
        )

    def _build_s3_bounces_table_func(self) -> str:
        web_bounces_table = create_s3_web_bounces_table(self.team.pk)
        return build_function_call(
            url=web_bounces_table.url,
            format=web_bounces_table.format,
            access_key=web_bounces_table.access_key,
            access_secret=web_bounces_table.access_secret,
            structure=web_bounces_table.structure,
        )

    def _execute_stats_query(self) -> Any:
        s3_table_func = self._build_s3_stats_table_func()

        query = f"""
        SELECT
            uniqMerge(persons_uniq_state) as unique_visitors,
            uniqMerge(sessions_uniq_state) as total_sessions,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        results = [tuple(row) for row in reader]

        return type("Result", (), {"results": results})()

    def _execute_bounces_query(self) -> Any:
        s3_table_func = self._build_s3_bounces_table_func()

        query = f"""
        SELECT
            sumMerge(bounces_count_state) as total_bounces,
            uniqMerge(sessions_uniq_state) as total_sessions
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        results = [tuple(row) for row in reader]

        return type("Result", (), {"results": results})()

    def _process_query_results(self, stats_result, bounces_result) -> dict[str, Any]:
        stats_data = stats_result.results[0] if stats_result.results else ["0", "0", "0"]
        bounces_data = bounces_result.results[0] if bounces_result.results else ["0", "0"]

        # Convert CSV string values to integers
        unique_visitors = int(stats_data[0]) if stats_data[0] else 0
        total_sessions = int(stats_data[1]) if stats_data[1] else 0
        total_pageviews = int(stats_data[2]) if stats_data[2] else 0

        total_bounces = int(bounces_data[0]) if bounces_data[0] else 0
        bounce_sessions = int(bounces_data[1]) if bounces_data[1] else 0

        bounce_rate = (total_bounces / bounce_sessions) if bounce_sessions > 0 else 0.0

        return {
            "unique_visitors": unique_visitors,
            "total_sessions": total_sessions,
            "total_pageviews": total_pageviews,
            "bounce_rate": round(bounce_rate, 3),
        }
