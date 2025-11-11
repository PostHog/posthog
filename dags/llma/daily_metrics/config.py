"""
Configuration for LLMA (LLM Analytics) metrics aggregation.

This module defines all parameters and constants used in the LLMA metrics pipeline.
Modify this file to add new metrics or change aggregation behavior.
"""

from dataclasses import dataclass


@dataclass
class LLMAConfig:
    """Configuration for LLMA metrics aggregation pipeline."""

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
AI_EVENT_TYPES = [
    "$ai_trace",
    "$ai_generation",
    "$ai_span",
    "$ai_embedding",
]


# Metric name transformation
# By default: "$ai_trace" -> "ai_trace_count"
# Customize this function if you need different naming
def get_metric_name(event_type: str) -> str:
    """Convert event type to metric name."""
    return f"{event_type.lstrip('$')}_count"


# Global config instance
config = LLMAConfig()
