from typing import Any
import structlog
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.query import create_default_modifiers_for_team, execute_hogql_query
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
                date_range=self.query.date_range,
                status="error",
            )

        try:
            context = self._setup_s3_context()

            stats_result = self._execute_stats_query(context)
            bounces_result = self._execute_bounces_query(context)

            results = self._process_query_results(stats_result, bounces_result)

            return WebAnalyticsExternalSummaryQueryResponse(
                data={
                    "unique_visitors": results["unique_visitors"],
                    "total_sessions": results["total_sessions"],
                    "total_pageviews": results["total_pageviews"],
                    "bounce_rate": results["bounce_rate"],
                },
                date_range=self.query.date_range,
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
                date_range=self.query.date_range,
                status="error",
            )

    @cached_property
    def can_use_s3_tables(self) -> bool:
        return self.team.organization.is_platform

    def _setup_s3_context(self) -> HogQLContext:
        web_stats_table = create_s3_web_stats_table(self.team.pk)
        web_bounces_table = create_s3_web_bounces_table(self.team.pk)

        database = create_hogql_database(team=self.team)

        database.add_warehouse_tables(web_stats_s3=web_stats_table, web_bounces_s3=web_bounces_table)

        return HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _execute_stats_query(self, context: HogQLContext) -> Any:
        query = f"""
        SELECT
            uniqMerge(persons_uniq_state) as unique_visitors,
            uniqMerge(sessions_uniq_state) as total_sessions,
            sumMerge(pageviews_count_state) as total_pageviews
        FROM web_stats_daily_s3
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        return execute_hogql_query(
            query,
            self.team,
            query_type="hogql_query",
            context=context,
            timings=self.timings,
            limit_context=self.limit_context,
        )

    def _execute_bounces_query(self, context: HogQLContext) -> Any:
        query = f"""
        SELECT
            sumMerge(bounces_count_state) as total_bounces,
            uniqMerge(sessions_uniq_state) as total_sessions
        FROM web_bounces_daily_s3
        WHERE team_id = {self.team.pk}
          AND period_bucket >= '{self.query_date_range.date_from_str}'
          AND period_bucket <= '{self.query_date_range.date_to_str}'
        """

        return execute_hogql_query(
            query,
            self.team,
            query_type="hogql_query",
            context=context,
            timings=self.timings,
            limit_context=self.limit_context,
        )

    def _process_query_results(self, stats_result, bounces_result) -> dict[str, Any]:
        stats_data = stats_result.results[0] if stats_result.results else [0, 0, 0]
        bounces_data = bounces_result.results[0] if bounces_result.results else [0, 0]

        unique_visitors = stats_data[0] or 0
        total_sessions = stats_data[1] or 0
        total_pageviews = stats_data[2] or 0

        total_bounces = bounces_data[0] or 0
        bounce_sessions = bounces_data[1] or 0

        bounce_rate = (total_bounces / bounce_sessions) if bounce_sessions > 0 else 0.0

        return {
            "unique_visitors": unique_visitors,
            "total_sessions": total_sessions,
            "total_pageviews": total_pageviews,
            "bounce_rate": round(bounce_rate, 3),
        }
