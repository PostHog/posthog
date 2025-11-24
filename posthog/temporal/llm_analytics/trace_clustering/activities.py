"""Activities for trace clustering workflow."""

import json
import uuid
import random
import logging
from datetime import UTC, datetime
from typing import Optional

import numpy as np
from temporalio import activity

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    calculate_trace_distances,
    determine_optimal_k,
    perform_kmeans_clustering,
    select_cluster_representatives,
)
from posthog.temporal.llm_analytics.trace_clustering.models import TraceEmbedding

logger = logging.getLogger(__name__)


@activity.defn
async def select_traces_for_clustering_activity(
    team_id: int,
    window_start: str,
    window_end: str,
    max_samples: int,
    random_seed: int | None = None,
) -> list[str]:
    """
    Query and sample trace IDs for clustering.

    This activity performs both querying and sampling in a single ClickHouse query,
    returning only trace IDs to keep the workflow payload small.

    Args:
        team_id: Team ID to query embeddings for
        window_start: Start of time window (RFC3339)
        window_end: End of time window (RFC3339)
        max_samples: Maximum number of traces to sample
        random_seed: Random seed for reproducibility (optional)

    Returns:
        List of trace IDs (strings)
    """
    from django.utils.dateparse import parse_datetime

    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    logger.info(f"Selecting up to {max_samples} trace IDs for team {team_id} from {window_start} to {window_end}")

    start_dt = parse_datetime(window_start)
    end_dt = parse_datetime(window_end)

    if not start_dt or not end_dt:
        raise ValueError(f"Invalid datetime format: {window_start} or {window_end}")

    # Query only trace_id with sampling done in ClickHouse
    # Use ORDER BY rand() for random sampling (or ORDER BY timestamp DESC if no sampling needed)
    if max_samples and max_samples > 0:
        query = """
            SELECT document_id as trace_id
            FROM posthog_document_embeddings
            WHERE team_id = %(team_id)s
                AND timestamp >= %(start_dt)s
                AND timestamp < %(end_dt)s
                AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
                AND length(embedding) > 0
            ORDER BY rand(%(seed)s)
            LIMIT %(max_samples)s
        """
        params = {
            "team_id": team_id,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
            "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
            "max_samples": max_samples,
            "seed": random_seed if random_seed is not None else 42,
        }
    else:
        query = """
            SELECT document_id as trace_id
            FROM posthog_document_embeddings
            WHERE team_id = %(team_id)s
                AND timestamp >= %(start_dt)s
                AND timestamp < %(end_dt)s
                AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
                AND length(embedding) > 0
            ORDER BY timestamp DESC
        """
        params = {
            "team_id": team_id,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
            "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
        }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    trace_ids = [row[0] for row in results]

    logger.info(f"Selected {len(trace_ids)} trace IDs")

    return trace_ids


@activity.defn
async def query_trace_embeddings_activity(
    team_id: int,
    window_start: str,
    window_end: str,
) -> list[TraceEmbedding]:
    """
    DEPRECATED: Use select_traces_for_clustering_activity instead.

    This activity is kept for backward compatibility but should not be used
    in new workflows as it passes large embedding objects through workflow history.
    """
    from django.utils.dateparse import parse_datetime

    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    logger.info(f"Querying trace embeddings for team {team_id} from {window_start} to {window_end}")

    start_dt = parse_datetime(window_start)
    end_dt = parse_datetime(window_end)

    if not start_dt or not end_dt:
        raise ValueError(f"Invalid datetime format: {window_start} or {window_end}")

    # Query only trace_id and embedding - metadata can be fetched by UI later
    query = """
        SELECT
            document_id as trace_id,
            embedding
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
        ORDER BY timestamp DESC
    """

    params = {
        "team_id": team_id,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    embeddings = []
    for row in results:
        trace_id, embedding = row
        embeddings.append(
            TraceEmbedding(
                trace_id=trace_id,
                embedding=embedding,
            )
        )

    logger.info(f"Found {len(embeddings)} trace embeddings")

    return embeddings


@activity.defn
async def sample_embeddings_activity(
    embeddings: list[TraceEmbedding],
    max_samples: int,
    random_seed: Optional[int] = None,
) -> list[TraceEmbedding]:
    """
    Sample embeddings randomly up to max_samples.

    If there are fewer embeddings than max_samples, returns all embeddings.
    Uses a fixed random seed for reproducibility within a run.

    Args:
        embeddings: List of trace embeddings
        max_samples: Maximum number of embeddings to sample
        random_seed: Random seed for reproducibility (defaults to run ID hash)

    Returns:
        Sampled list of embeddings
    """
    logger.info(f"Sampling up to {max_samples} embeddings from {len(embeddings)} total")

    if len(embeddings) <= max_samples:
        logger.info(f"Using all {len(embeddings)} embeddings (fewer than max_samples)")
        return embeddings

    # Use provided seed or generate from current time
    if random_seed is None:
        random_seed = int(datetime.now().timestamp())

    random.seed(random_seed)
    sampled = random.sample(embeddings, max_samples)

    logger.info(f"Sampled {len(sampled)} embeddings with seed {random_seed}")

    return sampled


@activity.defn
async def determine_optimal_k_activity(
    trace_ids: list[str],
    team_id: int,
    min_k: int,
    max_k: int,
) -> tuple[int, dict[int, float]]:
    """
    Determine optimal number of clusters using silhouette score.

    Fetches embeddings from ClickHouse by trace IDs, then tests k values
    from min_k to max_k and returns the k with highest silhouette score.

    Args:
        trace_ids: List of trace IDs to cluster
        team_id: Team ID (for fetching embeddings)
        min_k: Minimum k to test
        max_k: Maximum k to test

    Returns:
        Tuple of (optimal_k, scores_dict)
    """
    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    logger.info(f"Determining optimal k from {min_k} to {max_k} for {len(trace_ids)} embeddings")

    # Fetch embeddings by trace IDs
    query = """
        SELECT document_id, embedding
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND document_id IN %(trace_ids)s
            AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
    """
    params = {
        "team_id": team_id,
        "trace_ids": trace_ids,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    # Convert to numpy array
    embeddings_array = np.array([row[1] for row in results])

    optimal_k, scores = determine_optimal_k(embeddings_array, min_k, max_k)

    logger.info(f"Optimal k: {optimal_k} (scores: {scores})")

    return optimal_k, scores


@activity.defn
async def perform_clustering_activity(
    trace_ids: list[str],
    team_id: int,
    k: int,
) -> tuple[list[int], list[list[float]], float]:
    """
    Perform k-means clustering on trace embeddings.

    Fetches embeddings from ClickHouse by trace IDs, then performs k-means clustering.

    Args:
        trace_ids: List of trace IDs to cluster
        team_id: Team ID (for fetching embeddings)
        k: Number of clusters

    Returns:
        Tuple of (labels, centroids, inertia)
    """
    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    logger.info(f"Performing k-means clustering with k={k} on {len(trace_ids)} embeddings")

    # Fetch embeddings by trace IDs, preserving order
    query = """
        SELECT document_id, embedding
        FROM posthog_document_embeddings
        WHERE team_id = %(team_id)s
            AND document_id IN %(trace_ids)s
            AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
    """
    params = {
        "team_id": team_id,
        "trace_ids": trace_ids,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    results = sync_execute(query, params, workload=Workload.OFFLINE)

    # Create a mapping to preserve order
    embedding_map = {row[0]: row[1] for row in results}
    embeddings_array = np.array([embedding_map[trace_id] for trace_id in trace_ids if trace_id in embedding_map])

    labels, centroids, inertia = perform_kmeans_clustering(embeddings_array, k)

    logger.info(f"Clustering complete: {k} clusters, inertia={inertia:.2f}")

    return labels.tolist(), centroids.tolist(), inertia


@activity.defn
async def emit_cluster_events_activity(
    team_id: int,
    clustering_run_id: str,
    window_start: str,
    window_end: str,
    total_traces: int,
    sampled_traces: int,
    optimal_k: int,
    silhouette_score: float,
    inertia: float,
    labels: list[int],
    centroids: list[list[float]],
    trace_ids: list[str],
    cluster_labels: dict[int, dict[str, str]],
) -> int:
    """
    Emit $ai_trace_clusters event to ClickHouse.

    Creates a single event containing all clusters with trace IDs, centroids, and LLM-generated labels.
    The UI can fetch metadata for individual traces as needed.

    Args:
        team_id: Team ID
        clustering_run_id: Unique ID for this clustering run
        window_start: Start of time window
        window_end: End of time window
        total_traces: Total traces analyzed
        sampled_traces: Number of traces sampled
        optimal_k: Number of clusters
        silhouette_score: Clustering quality score
        inertia: K-means inertia
        labels: Cluster assignments
        centroids: Cluster centroids (center points in embedding space)
        embeddings: All embeddings (for getting trace IDs per cluster)
        cluster_labels: Dict mapping cluster_id -> {title, description}

    Returns:
        Number of events emitted (always 1)
    """

    logger.info(f"Emitting cluster event for team {team_id}, run {clustering_run_id}")

    def _emit():
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", extra={"team_id": team_id})
            raise ValueError(f"Team {team_id} not found")

        # Convert centroids to numpy for efficient distance computation
        centroids_array = np.array(centroids)

        # Fetch embeddings by trace IDs
        from posthog.clickhouse.client.connection import Workload
        from posthog.clickhouse.client.execute import sync_execute

        query = """
            SELECT document_id, embedding
            FROM posthog_document_embeddings
            WHERE team_id = %(team_id)s
                AND document_id IN %(trace_ids)s
                AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
                AND length(embedding) > 0
        """
        params = {
            "team_id": team_id,
            "trace_ids": trace_ids,
            "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
            "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
        }

        results = sync_execute(query, params, workload=Workload.OFFLINE)

        # Create mapping and preserve order
        embedding_map = {row[0]: row[1] for row in results}
        embeddings_array = np.array([embedding_map[trace_id] for trace_id in trace_ids if trace_id in embedding_map])

        # Compute distances from each trace to all centroids
        # Shape: (num_traces, num_clusters)
        distances_matrix = calculate_trace_distances(embeddings_array, centroids_array)

        # Build clusters array with centroids and trace distances
        clusters = []

        for cluster_id in range(optimal_k):
            # Get all trace IDs in this cluster with their distances
            cluster_traces = []
            for i, label in enumerate(labels):
                if label == cluster_id:
                    cluster_traces.append(
                        {
                            "trace_id": trace_ids[i],
                            "distance_to_centroid": float(distances_matrix[i][cluster_id]),
                            "distances_to_all_centroids": distances_matrix[i].tolist(),
                        }
                    )

            # Get labels for this cluster (with fallback)
            cluster_label = cluster_labels.get(cluster_id, {})
            title = cluster_label.get("title", f"Cluster {cluster_id}")
            description = cluster_label.get("description", "")

            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "size": len(cluster_traces),
                    "title": title,
                    "description": description,
                    "traces": cluster_traces,
                    "centroid": centroids[cluster_id],
                }
            )

        event_uuid = uuid.uuid4()
        event_timestamp = datetime.now(UTC)

        # Build event properties
        properties = {
            "$ai_clustering_version": constants.CLUSTERING_VERSION,
            "$ai_clustering_run_id": clustering_run_id,
            "$ai_team_id": team_id,
            "$ai_timestamp": event_timestamp.isoformat(),
            "$ai_window_start": window_start,
            "$ai_window_end": window_end,
            "$ai_total_traces_analyzed": total_traces,
            "$ai_sampled_traces_count": sampled_traces,
            "$ai_optimal_k": optimal_k,
            "$ai_silhouette_score": silhouette_score,
            "$ai_inertia": inertia,
            "$ai_clusters": json.dumps(clusters),
        }

        # Emit event
        create_event(
            event_uuid=event_uuid,
            event=constants.EVENT_NAME,
            team=team,
            distinct_id=f"trace_clustering_{team_id}",
            timestamp=event_timestamp,
            properties=properties,
            person_id=None,
        )

        logger.info(
            f"Emitted {constants.EVENT_NAME} event with {optimal_k} clusters, "
            f"{len(clusters)} cluster objects, {sampled_traces} total traces"
        )

        return 1

    return await database_sync_to_async(_emit, thread_sensitive=False)()


@activity.defn
async def generate_cluster_labels_activity(
    team_id: int,
    trace_ids: list[str],
    labels: list[int],
    centroids: list[list[float]],
    optimal_k: int,
    traces_per_cluster: int,
) -> dict[int, dict[str, str]]:
    """
    Generate titles and descriptions for all clusters using LLM.

    Strategy:
    1. For each cluster, select N traces nearest to centroid
    2. Fetch summaries for those traces from $ai_trace_summary events
    3. Send all clusters to LLM in one call for better global context
    4. LLM generates title + description for each cluster

    Args:
        team_id: Team ID
        embeddings: All trace embeddings (includes trace_id)
        labels: Cluster assignments for each embedding
        centroids: Cluster centroids
        optimal_k: Number of clusters
        traces_per_cluster: Number of representative traces to use per cluster

    Returns:
        Dict mapping cluster_id -> {title, description}
    """
    logger.info(f"Generating labels for {optimal_k} clusters using {traces_per_cluster} traces per cluster")

    def _generate():
        from posthog.clickhouse.client.connection import Workload
        from posthog.clickhouse.client.execute import sync_execute
        # Fetch embeddings for the trace IDs

        query = """
            SELECT document_id, embedding
            FROM posthog_document_embeddings
            WHERE team_id = %(team_id)s
                AND document_id IN %(trace_ids)s
                AND rendering IN (%(minimal_rendering)s, %(detailed_rendering)s)
                AND length(embedding) > 0
        """
        params = {
            "team_id": team_id,
            "trace_ids": trace_ids,
            "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
            "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
        }

        results = sync_execute(query, params, workload=Workload.OFFLINE)

        # Create mapping
        embedding_map = {row[0]: row[1] for row in results}
        embeddings_array = np.array([embedding_map[trace_id] for trace_id in trace_ids if trace_id in embedding_map])
        centroids_array = np.array(centroids)

        # For each cluster, find representative traces (nearest to centroid)
        # We only want closest traces for labeling to get the strongest signal
        cluster_trace_ids = select_cluster_representatives(
            embeddings_array,
            np.array(labels),
            centroids_array,
            trace_ids,
            n_closest=traces_per_cluster,
            n_random=0,
        )

        # Fetch summaries for all representative traces
        all_trace_ids = []
        for trace_ids in cluster_trace_ids.values():
            all_trace_ids.extend(trace_ids)

        if not all_trace_ids:
            logger.warning("No representative traces found, returning empty labels")
            return {}

        # Query $ai_trace_summary events for these traces
        query = """
            SELECT
                JSONExtractString(properties, '$ai_trace_id') as trace_id,
                JSONExtractString(properties, '$ai_summary_title') as title,
                JSONExtractString(properties, '$ai_summary_text_repr') as summary
            FROM events
            WHERE team_id = %(team_id)s
                AND event = '$ai_trace_summary'
                AND JSONExtractString(properties, '$ai_trace_id') IN %(trace_ids)s
        """

        results = sync_execute(query, {"team_id": team_id, "trace_ids": all_trace_ids}, workload=Workload.OFFLINE)

        # Build trace_id -> summary mapping
        trace_summaries = {row[0]: {"title": row[1], "summary": row[2]} for row in results}

        logger.info(f"Found {len(trace_summaries)} trace summaries for {len(all_trace_ids)} trace IDs")

        # Build prompt with all clusters
        clusters_data = []
        for cluster_id in range(optimal_k):
            trace_ids = cluster_trace_ids[cluster_id]
            cluster_size = sum(1 for label in labels if label == cluster_id)

            # Get summaries for this cluster's representative traces
            representative_traces = []
            for trace_id in trace_ids:
                if trace_id in trace_summaries:
                    representative_traces.append(
                        {
                            "trace_id": trace_id,
                            "title": trace_summaries[trace_id]["title"],
                            "summary": trace_summaries[trace_id]["summary"][:500],  # Truncate long summaries
                        }
                    )

            clusters_data.append(
                {"cluster_id": cluster_id, "size": cluster_size, "representative_traces": representative_traces}
            )

        # Build LLM prompt
        prompt = _build_cluster_labels_prompt(optimal_k, clusters_data)

        # Call LLM (using PostHog's OpenAI infrastructure)
        import os

        from django.conf import settings

        from posthoganalytics.ai.openai import OpenAI

        from posthog.cloud_utils import is_cloud
        from posthog.utils import get_instance_region

        # Validate environment
        if not settings.DEBUG and not is_cloud():
            raise Exception("AI features are only available in PostHog Cloud")

        if not os.environ.get("OPENAI_API_KEY"):
            raise Exception("OpenAI API key is not configured")

        # Create OpenAI client (sync, since _generate is sync)
        class _NoOpPostHogClient:
            privacy_mode = False

        client = OpenAI(
            posthog_client=_NoOpPostHogClient(),  # type: ignore[arg-type]
            timeout=120.0,
            base_url=getattr(settings, "OPENAI_BASE_URL", None),
        )

        # Prepare user param for tracking
        instance_region = get_instance_region() or "HOBBY"
        user_param = f"{instance_region}/{team_id}"

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Cheaper model for this task
                messages=[{"role": "user", "content": prompt}],
                user=user_param,
                response_format={"type": "json_object"},
            )

            # Parse the JSON response
            content = response.choices[0].message.content
            if not content:
                raise Exception("OpenAI returned empty response")
            result = json.loads(content)

            # Convert to dict[cluster_id -> {title, description}]
            labels_dict = {}
            for cluster in result.get("clusters", []):
                cluster_id = cluster.get("cluster_id")
                if cluster_id is not None:
                    labels_dict[cluster_id] = {
                        "title": cluster.get("title", f"Cluster {cluster_id}"),
                        "description": cluster.get("description", ""),
                    }

            logger.info(f"Generated labels for {len(labels_dict)} clusters")
            return labels_dict

        except Exception as e:
            logger.exception(f"Failed to generate cluster labels: {e}")
            # Return fallback labels
            return {
                cluster_id: {
                    "title": f"Cluster {cluster_id}",
                    "description": f"Cluster of {sum(1 for label in labels if label == cluster_id)} similar traces",
                }
                for cluster_id in range(optimal_k)
            }

    return await database_sync_to_async(_generate, thread_sensitive=False)()


def _build_cluster_labels_prompt(optimal_k: int, clusters_data: list[dict]) -> str:
    """Build the prompt for generating cluster labels."""
    prompt = f"""You are analyzing {optimal_k} clusters of similar LLM traces. For each cluster, provide a short title and description that captures what makes traces in that cluster similar.

Having context about ALL clusters helps you create more distinctive and useful labels that differentiate between clusters.

Here are the {optimal_k} clusters with their representative traces:

"""

    for cluster in clusters_data:
        prompt += f"\n## Cluster {cluster['cluster_id']} ({cluster['size']} traces)\n\n"
        prompt += "Representative traces (closest to cluster center):\n\n"

        for i, trace in enumerate(cluster["representative_traces"], 1):
            prompt += f"{i}. **{trace['title']}**\n"
            prompt += f"   Summary: {trace['summary']}\n\n"

    prompt += """
Based on these representative traces, provide a title and description for each cluster:

1. **Title**: 3-5 words that capture the main pattern (e.g., "PDF Generation Errors", "Authentication Flows", "Data Pipeline Processing")
2. **Description**: 1-2 sentences explaining what traces in this cluster have in common - focus on functionality, error patterns, API usage, or workflows

Respond with JSON in this exact format:
{
  "clusters": [
    {
      "cluster_id": 0,
      "title": "Short Pattern Title",
      "description": "Brief description of what these traces have in common."
    },
    {
      "cluster_id": 1,
      "title": "Another Pattern",
      "description": "What makes this cluster distinct from others."
    }
  ]
}

Make titles and descriptions distinctive - users need to quickly understand how clusters differ from each other.
"""
    return prompt
