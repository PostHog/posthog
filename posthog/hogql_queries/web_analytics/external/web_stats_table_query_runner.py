from typing import Any
import csv
from io import StringIO
from dataclasses import dataclass
from datetime import datetime
import structlog
import chdb
from posthog.hogql import ast
from posthog.hogql.database.s3_table import build_function_call
from posthog.hogql.database.schema.web_analytics_s3 import (
    create_s3_web_stats_table,
    create_s3_web_bounces_table,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.schema import (
    ExternalQueryErrorCode,
    ExternalQueryError,
    WebAnalyticsExternalWebStatsTableQuery,
    WebAnalyticsExternalWebStatsTableQueryResponse,
    ExternalQueryStatus,
    WebStatsBreakdown,
)


@dataclass
class QueryResult:
    rows: list[tuple[str, ...]]

    def first_row(self) -> tuple[str, ...]:
        return self.rows[0] if self.rows else ()


logger = structlog.get_logger(__name__)


class WebAnalyticsExternalWebStatsTableQueryRunner(QueryRunner):
    query: WebAnalyticsExternalWebStatsTableQuery
    response: WebAnalyticsExternalWebStatsTableQueryResponse

    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def calculate(self) -> WebAnalyticsExternalWebStatsTableQueryResponse:
        if not self.can_use_s3_tables:
            return WebAnalyticsExternalWebStatsTableQueryResponse(
                data={},
                error=ExternalQueryError(
                    code=ExternalQueryErrorCode.PLATFORM_ACCESS_REQUIRED,
                    detail="Organization must have platform access to use external web analytics",
                ),
                status=ExternalQueryStatus.ERROR,
            )

        try:
            stats_result = self._execute_stats_query()
            bounces_result = None

            if self.query.includeBounceRate:
                bounces_result = self._execute_bounces_query()

            results = self._process_query_results(stats_result, bounces_result)

            return WebAnalyticsExternalWebStatsTableQueryResponse(
                data=results,
                status=ExternalQueryStatus.SUCCESS,
            )

        except Exception as e:
            logger.error(
                "Platform web analytics stats table query failed", team_id=self.team.pk, error=str(e), exc_info=True
            )
            return WebAnalyticsExternalWebStatsTableQueryResponse(
                data={},
                error=ExternalQueryError(
                    code=ExternalQueryErrorCode.QUERY_EXECUTION_FAILED,
                    detail="Failed to execute query",
                ),
                status=ExternalQueryStatus.ERROR,
            )

    @cached_property
    def can_use_s3_tables(self) -> bool:
        return bool(self.team.organization.is_platform)

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

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

    def _get_breakdown_column(self) -> str:
        breakdown_mapping = {
            WebStatsBreakdown.PAGE: "page",
            WebStatsBreakdown.INITIAL_PAGE: "initial_page",
            WebStatsBreakdown.EXIT_PAGE: "exit_page",
            WebStatsBreakdown.UTM_SOURCE: "utm_source",
            WebStatsBreakdown.UTM_CAMPAIGN: "utm_campaign",
            WebStatsBreakdown.UTM_MEDIUM: "utm_medium",
            WebStatsBreakdown.UTM_TERM: "utm_term",
            WebStatsBreakdown.UTM_CONTENT: "utm_content",
            WebStatsBreakdown.COUNTRY: "country",
            WebStatsBreakdown.REGION: "region",
            WebStatsBreakdown.CITY: "city",
            WebStatsBreakdown.BROWSER: "browser",
            WebStatsBreakdown.OS: "os",
            WebStatsBreakdown.DEVICE_TYPE: "device_type",
            WebStatsBreakdown.VIEWPORT: "viewport",
        }
        return breakdown_mapping.get(self.query.breakdownBy, "page")

    def _execute_stats_query(self) -> QueryResult:
        s3_table_func = self._build_s3_stats_table_func()
        breakdown_column = self._get_breakdown_column()

        query = f"""
        SELECT
            {breakdown_column} as breakdown_value,
            uniqMerge(persons_uniq_state) as unique_visitors,
            uniqMerge(sessions_uniq_state) as total_sessions,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        GROUP BY {breakdown_column}
        ORDER BY total_pageviews DESC
        """

        if self.query.limit:
            query += f" LIMIT {self.query.limit}"

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        rows = [tuple(row) for row in reader]

        return QueryResult(rows=rows)

    def _execute_bounces_query(self) -> QueryResult:
        s3_table_func = self._build_s3_bounces_table_func()
        breakdown_column = self._get_breakdown_column()

        query = f"""
        SELECT
            {breakdown_column} as breakdown_value,
            sumMerge(bounces_count_state) as total_bounces,
            uniqMerge(sessions_uniq_state) as bounce_sessions
        FROM {s3_table_func}
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        GROUP BY {breakdown_column}
        """

        chdb_result = chdb.query(query, output_format="CSV")
        reader = csv.reader(StringIO(str(chdb_result)))
        rows = [tuple(row) for row in reader]

        return QueryResult(rows=rows)

    def _process_query_results(self, stats_result: QueryResult, bounces_result: QueryResult | None) -> dict[str, Any]:
        # Process stats data
        stats_data = {}
        for row in stats_result.rows:
            if len(row) >= 4:
                breakdown_value = row[0] if row[0] else ""
                stats_data[breakdown_value] = {
                    "breakdown_value": breakdown_value,
                    "unique_visitors": int(row[1]) if row[1] else 0,
                    "total_sessions": int(row[2]) if row[2] else 0,
                    "total_pageviews": int(row[3]) if row[3] else 0,
                }

        # Process bounces data if available
        bounces_data = {}
        if bounces_result:
            for row in bounces_result.rows:
                if len(row) >= 3:
                    breakdown_value = row[0] if row[0] else ""
                    bounces_data[breakdown_value] = {
                        "total_bounces": int(row[1]) if row[1] else 0,
                        "bounce_sessions": int(row[2]) if row[2] else 0,
                    }

        # Combine data
        results = []
        for breakdown_value, stats in stats_data.items():
            result = {
                "breakdown_value": breakdown_value,
                "unique_visitors": stats["unique_visitors"],
                "total_sessions": stats["total_sessions"],
                "total_pageviews": stats["total_pageviews"],
            }

            if self.query.includeBounceRate and breakdown_value in bounces_data:
                bounce_data = bounces_data[breakdown_value]
                bounce_rate = (
                    (bounce_data["total_bounces"] / bounce_data["bounce_sessions"])
                    if bounce_data["bounce_sessions"] > 0
                    else 0.0
                )
                result["bounce_rate"] = round(bounce_rate, 3)

            results.append(result)

        return {
            "results": results,
            "breakdown_by": self.query.breakdownBy,
            "total_results": len(results),
        }
