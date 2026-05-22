"""Unit tests for the MCPA clustering metrics interceptor surface.

These tests assert the configuration shape (workflow/activity types,
histogram metric names) rather than end-to-end metric emission — Prometheus
output is exercised by the worker's own integration tests.
"""

from posthog.temporal.mcp_analytics.intent_clustering.constants import COORDINATOR_WORKFLOW_NAME, WORKFLOW_NAME
from posthog.temporal.mcp_analytics.intent_clustering.metrics import (
    MCPA_CLUSTERING_ACTIVITY_TYPES,
    MCPA_CLUSTERING_LATENCY_HISTOGRAM_BUCKETS,
    MCPA_CLUSTERING_LATENCY_HISTOGRAM_METRICS,
    MCPA_CLUSTERING_WORKFLOW_TYPES,
    MCPAClusteringMetricsInterceptor,
)


class TestInterceptorConfig:
    def test_task_queue_targets_mcpa(self) -> None:
        from django.conf import settings

        assert MCPAClusteringMetricsInterceptor.task_queue == settings.MCPA_TASK_QUEUE

    def test_activity_types_include_compute_and_discovery(self) -> None:
        assert "compute_intent_clusters_activity" in MCPA_CLUSTERING_ACTIVITY_TYPES
        assert "get_team_ids_for_mcp_analytics" in MCPA_CLUSTERING_ACTIVITY_TYPES

    def test_workflow_types_include_both_workflows(self) -> None:
        assert WORKFLOW_NAME in MCPA_CLUSTERING_WORKFLOW_TYPES
        assert COORDINATOR_WORKFLOW_NAME in MCPA_CLUSTERING_WORKFLOW_TYPES

    def test_histogram_metric_names_are_prefixed(self) -> None:
        # Prefix is load-bearing for Grafana dashboards — if anyone renames
        # the prefix, the dashboards stop working silently.
        for name in MCPA_CLUSTERING_LATENCY_HISTOGRAM_METRICS:
            assert name.startswith("mcpa_clustering_"), name

    def test_histogram_buckets_cover_workflow_and_activity_ranges(self) -> None:
        # Workflows can run up to 30 min (WORKFLOW_EXECUTION_TIMEOUT in
        # constants); the bucket list needs an upper bucket >= that timeout.
        assert max(MCPA_CLUSTERING_LATENCY_HISTOGRAM_BUCKETS) >= 30 * 60 * 1_000
        # Sub-second buckets matter for the per-stage heartbeats.
        assert min(MCPA_CLUSTERING_LATENCY_HISTOGRAM_BUCKETS) <= 1_000
