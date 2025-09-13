from datetime import datetime
from typing import Optional

from django.core.cache import cache

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.pre_aggregated.utils import get_stats_table
from posthog.logging.timing import timed
from posthog.models.team import Team
from posthog.utils import generate_cache_key, get_safe_cache


class WebAnalyticsPreAggregatedDateRange:
    def __init__(self, team: Team, use_v2_tables: bool = False) -> None:
        self.team = team
        self.use_v2_tables = use_v2_tables
        self.logger = structlog.get_logger(__name__)

    def get_available_date_range(self) -> Optional[tuple[datetime, datetime]]:
        cached_result = self._get_cached_date_range()
        if cached_result:
            return cached_result

        try:
            return self._query_and_cache_date_range()
        except Exception as e:
            self.logger.exception(
                "Failed to get web analytics date range",
                error=str(e),
                team_id=self.team.pk,
                use_v2_tables=self.use_v2_tables,
            )
            return None

    def is_date_range_pre_aggregated(self, date_from: datetime, date_to: datetime) -> bool:
        available_range = self.get_available_date_range()
        if not available_range:
            return False

        available_start, available_end = available_range
        return date_from >= available_start and date_to <= available_end

    def _get_cached_date_range(self) -> Optional[tuple[datetime, datetime]]:
        cache_key = self._get_cache_key()
        cached_result = get_safe_cache(cache_key)
        if cached_result:
            return (
                datetime.fromisoformat(cached_result["min_date"]),
                datetime.fromisoformat(cached_result["max_date"]),
            )
        return None

    @timed("web_analytics_date_range_query")
    def _query_and_cache_date_range(self) -> Optional[tuple[datetime, datetime]]:
        query = self._build_date_range_query()

        response = execute_hogql_query(
            query_type="web_analytics_date_range_query",
            query=query,
            team=self.team,
            limit_context=None,
        )

        result = self._extract_date_range_from_response(response)
        if result:
            self._cache_date_range_result(result)
        return result

    def _build_date_range_query(self):
        # Let's use the stats table for a simpler query as it is the most complex table to build, so
        # in theory it should be the one that has more reliable data (aka: inserts did not fail)
        # If needed we can make this more complex by checking the longest sequence of dates or
        # min/max dates that exist on both/all tables
        table_name = get_stats_table(self.use_v2_tables)

        return parse_select(
            """
            SELECT
                min(toTimeZone(period_bucket, 'UTC')) as min_date,
                max(toTimeZone(period_bucket, 'UTC')) as max_date
            FROM {table}
            WHERE team_id = {team_id}
            """,
            placeholders={
                "table": ast.Field(chain=[table_name]),
                "team_id": ast.Constant(value=self.team.pk),
            },
        )

    def _extract_date_range_from_response(self, response) -> Optional[tuple[datetime, datetime]]:
        if not response.results or not response.results[0] or not response.results[0][0]:
            return None

        min_date, max_date = response.results[0]
        if min_date and max_date:
            return (min_date, max_date)
        return None

    def _cache_date_range_result(self, result: tuple[datetime, datetime]) -> None:
        cache_key = self._get_cache_key()
        min_date, max_date = result
        cache.set(
            cache_key,
            {
                "min_date": min_date.isoformat(),
                "max_date": max_date.isoformat(),
            },
            1800,  # 30 minutes cache
        )

    def _get_cache_key(self) -> str:
        return generate_cache_key(f"web_analytics_date_range_{self.team.pk}_{self.use_v2_tables}_{self.team.timezone}")
