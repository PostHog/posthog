"""
Configuration for LLMA (LLM Analytics) metrics aggregation.

This module defines all parameters and constants used in the LLMA metrics pipeline.
Modify this file to add new metrics or change aggregation behavior.
"""

from dataclasses import dataclass


@dataclass
class LLMADailyMetricsConfig:
    """Configuration for LLMA daily metrics aggregation pipeline."""

    # ClickHouse table name
    table_name: str = "llma_metrics_daily"

    # Start date for daily partitions (when AI events were introduced)
    partition_start_date: str = "2025-01-01"

    # Schedule: Daily at 6 AM UTC
    cron_schedule: str = "0 6 * * *"

    # Backfill policy: process N days per run
    max_partitions_per_run: int = 14

    # ClickHouse query settings
    clickhouse_max_execution_time: int = 300  # 5 minutes

    # Dagster job timeout (seconds)
    job_timeout: int = 1800  # 30 minutes

    # Include error rate metrics (percentage of events with errors)
    include_error_rates: bool = True

    # AI event types to track
    # Add new event types here to automatically include them in daily aggregations
    ai_event_types: list[str] | None = None

    # Pageview URL path to metric name mappings
    # Maps URL patterns to metric names for tracking pageviews
    # Order matters: more specific patterns should come before general ones
    pageview_mappings: list[tuple[str, str]] | None = None

    def __post_init__(self):
        """Set default values for list fields."""
        if self.ai_event_types is None:
            self.ai_event_types = [
                "$ai_trace",
                "$ai_generation",
                "$ai_span",
                "$ai_embedding",
            ]
        if self.pageview_mappings is None:
            self.pageview_mappings = [
                ("/llm-analytics/traces", "traces"),
                ("/llm-analytics/generations", "generations"),
                ("/llm-analytics/users", "users"),
                ("/llm-analytics/sessions", "sessions"),
                ("/llm-analytics/playground", "playground"),
                ("/llm-analytics/datasets", "datasets"),
                ("/llm-analytics/evaluations", "evaluations"),
            ]


# Global config instance
config = LLMADailyMetricsConfig()
