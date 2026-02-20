"""Shared Prometheus metrics for LLMA coordinator workflows.

Used by both the summarization and clustering coordinators to track
team discovery and per-team success/failure across pipeline runs.
"""

from posthog.temporal.llm_analytics.metrics import get_metric_meter


def record_teams_discovered(count: int, pipeline: str, analysis_level: str) -> None:
    meter = get_metric_meter({"pipeline": pipeline, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_coordinator_teams_discovered",
        "Teams discovered by coordinator",
    ).add(count)


def increment_team_succeeded(pipeline: str, analysis_level: str) -> None:
    meter = get_metric_meter({"pipeline": pipeline, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_coordinator_team_succeeded",
        "Teams that completed successfully",
    ).add(1)


def increment_team_failed(pipeline: str, analysis_level: str) -> None:
    meter = get_metric_meter({"pipeline": pipeline, "analysis_level": analysis_level})
    meter.create_counter(
        "llma_coordinator_team_failed",
        "Teams that failed processing",
    ).add(1)
