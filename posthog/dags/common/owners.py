from enum import Enum


class JobOwners(str, Enum):
    TEAM_ANALYTICS_PLATFORM = "team-analytics-platform"
    TEAM_BILLING = "team-billing"
    TEAM_CLICKHOUSE = "team-clickhouse"
    TEAM_DATA_STACK = "team-data-stack"
    TEAM_ERROR_TRACKING = "team-error-tracking"

    TEAM_GROWTH = "team-growth"
    TEAM_INGESTION = "team-ingestion"
    TEAM_LLM_ANALYTICS = "team-llm-analytics"
    TEAM_POSTHOG_AI = "team-posthog-ai"
    TEAM_REVENUE_ANALYTICS = "team-revenue-analytics"
    TEAM_WEB_ANALYTICS = "team-web-analytics"
