from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsQuery,
    FunnelsQuery,
    HogQLQuery,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsTopCustomersQuery,
    StickinessQuery,
    TrendsQuery,
)

from .funnel import FunnelResultsFormatter
from .retention import RetentionResultsFormatter
from .revenue_analytics import (
    RevenueAnalyticsGrossRevenueResultsFormatter,
    RevenueAnalyticsMetricsResultsFormatter,
    RevenueAnalyticsMRRResultsFormatter,
    RevenueAnalyticsTopCustomersResultsFormatter,
)
from .sql import TRUNCATED_MARKER, SQLResultsFormatter
from .stickiness import StickinessResultsFormatter
from .trends import TrendsResultsFormatter

if TYPE_CHECKING:
    from posthog.models import Team


def format_query_results_for_llm(
    query: BaseModel,
    response: dict[str, Any],
    team: "Team",
    utc_now: datetime | None = None,
) -> str | None:
    """
    Format query results into LLM-friendly text.

    This is a synchronous function that dispatches to the appropriate formatter
    based on query type. Returns None if the query type is not supported.
    """
    if utc_now is None:
        utc_now = datetime.now(UTC)

    if isinstance(query, AssistantTrendsQuery | TrendsQuery):
        return TrendsResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
        return FunnelResultsFormatter(query, response["results"], team, utc_now).format()
    elif isinstance(query, AssistantStickinessQuery | StickinessQuery):
        return StickinessResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantRetentionQuery | RetentionQuery):
        return RetentionResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantHogQLQuery | HogQLQuery):
        return SQLResultsFormatter(query, response["results"], response["columns"]).format()
    elif isinstance(query, RevenueAnalyticsGrossRevenueQuery):
        return RevenueAnalyticsGrossRevenueResultsFormatter(query, response["results"]).format()
    elif isinstance(query, RevenueAnalyticsMetricsQuery):
        return RevenueAnalyticsMetricsResultsFormatter(query, response["results"]).format()
    elif isinstance(query, RevenueAnalyticsMRRQuery):
        return RevenueAnalyticsMRRResultsFormatter(query, response["results"]).format()
    elif isinstance(query, RevenueAnalyticsTopCustomersQuery):
        return RevenueAnalyticsTopCustomersResultsFormatter(query, response["results"]).format()

    return None


__all__ = [
    "FunnelResultsFormatter",
    "RetentionResultsFormatter",
    "SQLResultsFormatter",
    "StickinessResultsFormatter",
    "TrendsResultsFormatter",
    "RevenueAnalyticsGrossRevenueResultsFormatter",
    "RevenueAnalyticsMetricsResultsFormatter",
    "RevenueAnalyticsMRRResultsFormatter",
    "RevenueAnalyticsTopCustomersResultsFormatter",
    "TRUNCATED_MARKER",
    "format_query_results_for_llm",
]
