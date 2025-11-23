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

from posthog.temporal.common.client import sync_connect
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
    from django.utils import timezone

    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    end_dt = timezone.now()
    start_dt = end_dt - timezone.timedelta(days=lookback_days)

    query = """
        SELECT
            team_id,
            count(DISTINCT document_id) as embedding_count
        FROM document_embeddings
        WHERE timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND rendering_type IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
        GROUP BY team_id
        HAVING embedding_count >= %(min_embeddings)s
        ORDER BY embedding_count DESC
    """

    params = {
        "start_dt": start_dt,
        "end_dt": end_dt,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
        "min_embeddings": min_embeddings,
    }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    if not results:
        print(f"\nNo teams found with at least {min_embeddings} embeddings in the last {lookback_days} days.")
        print("You need to run the batch trace summarization workflow first to generate embeddings.")
        return []

    print(f"\nTeams with embeddings (last {lookback_days} days):")
    print("=" * 60)
    for team_id, count in results:
        print(f"Team ID: {team_id:4d}  |  Embeddings: {count:5d}")
    print("=" * 60)
    print(f"Total teams: {len(results)}")

    return [team_id for team_id, _ in results]


def trigger_clustering(
    team_id: int,
    lookback_days: int | None = None,
    max_samples: int | None = None,
    min_k: int | None = None,
    max_k: int | None = None,
    samples_per_cluster: int | None = None,
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
        samples_per_cluster: Representative traces per cluster (default: 7)
        window_start: Explicit window start in RFC3339 format (overrides lookback_days)
        window_end: Explicit window end in RFC3339 format (overrides lookback_days)
        wait: Wait for workflow to complete (default: True)

    Returns:
        dict: Workflow result if wait=True, WorkflowHandle if wait=False
    """
    client = sync_connect()

    inputs = ClusteringInputs(
        team_id=team_id,
        lookback_days=lookback_days if lookback_days is not None else constants.DEFAULT_LOOKBACK_DAYS,
        max_samples=max_samples if max_samples is not None else constants.DEFAULT_MAX_SAMPLES,
        min_k=min_k if min_k is not None else constants.DEFAULT_MIN_K,
        max_k=max_k if max_k is not None else constants.DEFAULT_MAX_K,
        samples_per_cluster=(
            samples_per_cluster if samples_per_cluster is not None else constants.DEFAULT_SAMPLES_PER_CLUSTER
        ),
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
    print(f"  - Samples per cluster: {inputs.samples_per_cluster}")
    if window_start:
        print(f"  - Window: {window_start} to {window_end}")
    print("=" * 60)

    if wait:
        result = client.execute_workflow(
            "daily-trace-clustering",
            inputs,
            id=workflow_id,
            task_queue="general-purpose-queue",
            execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
        )

        print("\n✅ Clustering completed!")
        print("=" * 60)
        print(f"Clustering run ID: {result.clustering_run_id}")
        print(f"Traces analyzed: {result.total_traces_analyzed}")
        print(f"Traces sampled: {result.sampled_traces_count}")
        print(f"Optimal k: {result.optimal_k}")
        print(f"Silhouette score: {result.silhouette_score:.4f}")
        print(f"Inertia: {result.inertia:.2f}")
        print(f"\nClusters:")
        for cluster in result.clusters:
            print(f"  - Cluster {cluster.cluster_id}: {cluster.size} traces")
        print(f"\nDuration: {result.duration_seconds:.2f}s")
        print("=" * 60)

        return result
    else:
        handle = client.start_workflow(
            "daily-trace-clustering",
            inputs,
            id=workflow_id,
            task_queue="general-purpose-queue",
            execution_timeout=constants.WORKFLOW_EXECUTION_TIMEOUT,
        )

        print(f"\n✅ Workflow started: {handle.id}")
        print(f"Check Temporal UI: http://localhost:8233/namespaces/default/workflows/{handle.id}")

        return handle


if __name__ == "__main__":
    # Quick test when run directly
    print("Finding teams with embeddings...")
    teams = find_teams_with_embeddings()

    if teams:
        print(f"\nTo trigger clustering for team {teams[0]}, run:")
        print(f">>> trigger_clustering(team_id={teams[0]})")
