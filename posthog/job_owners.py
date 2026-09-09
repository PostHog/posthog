from enum import Enum


class JobOwners(str, Enum):
    """Team that owns a scheduled job, used for alert routing.

    Lives outside `posthog.dags` because Temporal and product code tag jobs with it too, and
    importing anything under `posthog.dags` runs that package's Django bootstrap.
    """

    TEAM_ANALYTICS_PLATFORM = "team-analytics-platform"
    TEAM_BILLING = "team-billing"
    TEAM_CLICKHOUSE = "team-clickhouse"
    TEAM_DATA_MODELING = "team-data-modeling"
    TEAM_DATA_STACK = "team-data-stack"
    TEAM_DATA_TOOLS = "team-data-tools"
    TEAM_ERROR_TRACKING = "team-error-tracking"
    TEAM_GROWTH = "team-growth"
    TEAM_INGESTION = "team-ingestion"
    TEAM_LOGS = "team-logs"
    TEAM_AI_OBSERVABILITY = "team-ai-observability"
    TEAM_MANAGED_WAREHOUSE = "team-managed-warehouse"
    TEAM_POSTHOG_AI = "team-posthog-ai"
    TEAM_QUERY_PERFORMANCE = "team-query-performance"
    TEAM_SECURITY = "team-security"
    TEAM_SELF_DRIVING = "team-self-driving"
    TEAM_WAREHOUSE_SOURCES = "team-warehouse-sources"
    TEAM_WEB_ANALYTICS = "team-web-analytics"
