from enum import Enum


class JobOwners(str, Enum):
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
    TEAM_LLM_ANALYTICS = "team-llm-analytics"
    TEAM_MANAGED_WAREHOUSE = "team-managed-warehouse"
    TEAM_POSTHOG_AI = "team-posthog-ai"
    TEAM_REVENUE_ANALYTICS = "team-revenue-analytics"
    TEAM_WAREHOUSE_SOURCES = "team-warehouse-sources"
    TEAM_WEB_ANALYTICS = "team-web-analytics"
