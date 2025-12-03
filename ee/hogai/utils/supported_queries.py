from posthog.schema import (
    FunnelsQuery,
    HogQLQuery,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsTopCustomersQuery,
    TrendsQuery,
)

from ee.hogai.utils.types.base import AnyAssistantSupportedQuery

# Build mapping of query kind names to their model classes for validation
# Use the 'kind' field value (e.g., "TrendsQuery") as the key
# NOTE: This needs to be kept in sync with the schema
SUPPORTED_QUERY_MODEL_BY_KIND: dict[str, type[AnyAssistantSupportedQuery]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "RetentionQuery": RetentionQuery,
    "HogQLQuery": HogQLQuery,
    "RevenueAnalyticsGrossRevenueQuery": RevenueAnalyticsGrossRevenueQuery,
    "RevenueAnalyticsMetricsQuery": RevenueAnalyticsMetricsQuery,
    "RevenueAnalyticsMRRQuery": RevenueAnalyticsMRRQuery,
    "RevenueAnalyticsTopCustomersQuery": RevenueAnalyticsTopCustomersQuery,
}
