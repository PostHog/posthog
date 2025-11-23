"""
Manual trigger helpers for trace clustering.

Helper functions for manually triggering the trace clustering workflow
for testing, development, and debugging purposes.

Usage:
    # From Django shell:
    python manage.py shell
    >>> from posthog.temporal.llm_analytics.trace_clustering.manual_trigger import trigger_clustering, find_teams_with_embeddings

    # Find teams with embeddings:
    >>> find_teams_with_embeddings()

    # Trigger clustering for a specific team:
    >>> trigger_clustering(team_id=1)

    # With custom parameters:
    >>> trigger_clustering(team_id=1, lookback_days=14, max_samples=5000)
"""
# ruff: noqa: T201

from datetime import datetime

from django.conf import settings

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs


def find_teams_with_embeddings(lookback_days: int = 7, min_embeddings: int = 20):
    """Find teams that have trace embeddings in the lookback window.

    Args:
        lookback_days: Days of history to check
        min_embeddings: Minimum number of embeddings required

    Returns:
        List of team IDs with sufficient embeddings
    """
    from posthog.temporal.llm_analytics.trace_clustering.coordinator import query_teams_with_embeddings

    team_ids = query_teams_with_embeddings(lookback_days, min_embeddings)

    if not team_ids:
        print(f"\nNo teams found with at least {min_embeddings} embeddings in the last {lookback_days} days.")
        print("You need to run the batch trace summarization workflow first to generate embeddings.")
        return []

    print(f"\nTeams with embeddings (last {lookback_days} days):")
    print("=" * 60)
    print(f"Found {len(team_ids)} team(s): {team_ids}")
    print("=" * 60)

    return team_ids


def trigger_clustering(
    team_id: int,
    lookback_days: int | None = None,
    max_samples: int | None = None,
    min_k: int | None = None,
    max_k: int | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    wait: bool = True,
):
    """
    Trigger the trace clustering workflow for a specific team.

    Args:
        team_id: Team ID to cluster traces for
        lookback_days: Days of trace history to analyze (default: 7)
        max_samples: Maximum embeddings to sample (default: 2000)
        min_k: Minimum k to test (default: 3)
        max_k: Maximum k to test (default: 6)
        window_start: Explicit window start in RFC3339 format (overrides lookback_days)
        window_end: Explicit window end in RFC3339 format (overrides lookback_days)
        wait: Wait for workflow to complete (default: True)

    Returns:
        dict: Workflow result if wait=True, WorkflowHandle if wait=False
    """
    inputs = ClusteringInputs(
        team_id=team_id,
        lookback_days=lookback_days if lookback_days is not None else constants.DEFAULT_LOOKBACK_DAYS,
        max_samples=max_samples if max_samples is not None else constants.DEFAULT_MAX_SAMPLES,
        min_k=min_k if min_k is not None else constants.DEFAULT_MIN_K,
        max_k=max_k if max_k is not None else constants.DEFAULT_MAX_K,
        window_start=window_start,
        window_end=window_end,
    )

    workflow_id = f"trace-clustering-team-{team_id}-{datetime.now().isoformat()}"

    print(f"\nTriggering trace clustering for team {team_id}...")
    print("=" * 60)
    print(f"Workflow ID: {workflow_id}")
    print(f"Parameters:")
    print(f"  - Lookback days: {inputs.lookback_days}")
    print(f"  - Max samples: {inputs.max_samples}")
    print(f"  - K range: [{inputs.min_k}, {inputs.max_k}]")
    if window_start:
        print(f"  - Window: {window_start} to {window_end}")
    print("=" * 60)

    if wait:
        print("⏳ Executing workflow (this may take a while)...\n")

        async def _execute():
            async_client = await async_connect()
            return await async_client.execute_workflow(
                "daily-trace-clustering",
                inputs,
                id=workflow_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
            )

        result = async_to_sync(_execute)()

        print("\n✅ Clustering completed!")
        print("=" * 60)
        print(f"Clustering run ID: {result.get('clustering_run_id', 'N/A')}")
        print(f"Traces analyzed: {result.get('total_traces_analyzed', 0)}")
        print(f"Traces sampled: {result.get('sampled_traces_count', 0)}")
        print(f"Optimal k: {result.get('optimal_k', 0)}")
        print(f"Silhouette score: {result.get('silhouette_score', 0):.4f}")
        print(f"Inertia: {result.get('inertia', 0):.2f}")

        clusters = result.get("clusters", [])
        if clusters:
            print(f"\nClusters:")
            for cluster in clusters:
                print(f"  - Cluster {cluster.get('cluster_id', 'N/A')}: {cluster.get('size', 0)} traces")

        print(f"\nDuration: {result.get('duration_seconds', 0):.2f}s")
        print("=" * 60)

        return result
    else:
        print("🚀 Starting workflow (non-blocking)...\n")

        async def _start():
            async_client = await async_connect()
            return await async_client.start_workflow(
                "daily-trace-clustering",
                inputs,
                id=workflow_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
            )

        handle = async_to_sync(_start)()

        print(f"\n✅ Workflow started: {handle.id}")
        print(f"Check Temporal UI: http://localhost:8081/namespaces/default/workflows/{handle.id}")

        return handle


if __name__ == "__main__":
    # Quick test when run directly
    print("Finding teams with embeddings...")
    teams = find_teams_with_embeddings()

    if teams:
        print(f"\nTo trigger clustering for team {teams[0]}, run:")
        print(f">>> trigger_clustering(team_id={teams[0]})")
