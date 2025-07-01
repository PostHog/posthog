import os
from posthog.settings.base_variables import DEBUG
from typing import Optional
from dagster import Backoff, Field, Array, Jitter, RetryPolicy

# TODO: Remove this once we're fully rolled out but this is better than defaulting to all teams
TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED = [1, 2, 55348, 47074, 12669, 1589, 117126]
TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS = os.getenv("TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS", 1 if DEBUG else 2)

web_analytics_retry_policy_def = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

# Shared ClickHouse settings for web analytics pre-aggregation
CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1600",
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
    "s3_truncate_on_insert": "1",
}

# Lighter settings for hourly processing (more frequent, smaller time windows)
CLICKHOUSE_SETTINGS_HOURLY = {
    "max_execution_time": "300",
    "max_bytes_before_external_group_by": "21474836480",
    "distributed_aggregation_memory_efficient": "1",
}


def format_clickhouse_settings(settings_dict: dict[str, str]) -> str:
    """Convert a settings dictionary to ClickHouse settings string format."""
    return ",".join([f"{key}={value}" for key, value in settings_dict.items()])


def merge_clickhouse_settings(base_settings: dict[str, str], extra_settings: Optional[str] = None) -> str:
    """Merge base settings with extra settings string and return formatted string."""
    settings = base_settings.copy()

    if extra_settings:
        # Parse extra settings string and merge
        for setting in extra_settings.split(","):
            if "=" in setting:
                key, value = setting.strip().split("=", 1)
                settings[key.strip()] = value.strip()

    return format_clickhouse_settings(settings)


# Shared config schema for daily processing
WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
        description="List of team IDs to process - if empty, processes all teams",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
}
