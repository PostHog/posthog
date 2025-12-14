"""LLM-based cluster labeling for trace clustering workflow.

This module contains functions for generating human-readable cluster labels
using LLM to create titles and descriptions based on representative traces.
"""

import os
from datetime import datetime

from django.conf import settings

import numpy as np
import openai
import structlog
from pydantic import BaseModel

from posthog.cloud_utils import is_cloud
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering.constants import LABELING_LLM_MODEL, LABELING_LLM_TIMEOUT
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_trace_summaries
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterLabel, ClusterRepresentatives
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


class ClusterLabelModel(BaseModel):
    cluster_id: int
    title: str
    description: str


class ClusterLabelsResponse(BaseModel):
    clusters: list[ClusterLabelModel]


def generate_cluster_labels(
    team: Team,
    labels: np.ndarray,
    representative_trace_ids: ClusterRepresentatives,
    window_start: datetime,
    window_end: datetime,
) -> dict[int, ClusterLabel]:
    """Generate titles and descriptions for all clusters using LLM.

    Strategy:
    1. Fetch summaries for representative traces from $ai_trace_summary events using HogQL
    2. Send all clusters to LLM in one call for better global context
    3. LLM generates title + description for each cluster

    Args:
        team: Team object for HogQL queries
        labels: Cluster assignments for each trace (used for cluster sizes)
        representative_trace_ids: Dict mapping cluster_id to list of representative trace IDs
        window_start: Start of time window
        window_end: End of time window

    Returns:
        Dict mapping cluster_id -> ClusterLabel
    """
    num_clusters = len(np.unique(labels))

    representative_trace_summaries = fetch_trace_summaries(
        team=team,
        trace_ids=[tid for tids in representative_trace_ids.values() for tid in tids],
        window_start=window_start,
        window_end=window_end,
    )

    clusters_data = []
    for cluster_id in range(num_clusters):
        trace_ids_in_cluster = representative_trace_ids.get(cluster_id, [])

        representative_traces = []
        for trace_id in trace_ids_in_cluster:
            if trace_id in representative_trace_summaries:
                representative_traces.append(representative_trace_summaries[trace_id])

        clusters_data.append(
            {
                "cluster_id": cluster_id,
                "size": int((labels == cluster_id).sum()),
                "representative_traces": representative_traces,
            }
        )

    prompt = _build_cluster_labels_prompt(num_clusters, clusters_data)

    return _call_llm_for_labels(prompt, team.id, num_clusters, labels)


def _build_cluster_labels_prompt(num_clusters: int, clusters_data: list[dict]) -> str:
    """Build the prompt for generating cluster labels.

    Args:
        num_clusters: Number of clusters
        clusters_data: List of dicts with cluster_id, size, and representative_traces

    Returns:
        Formatted prompt string for LLM
    """
    prompt = f"""You are analyzing {num_clusters} clusters of similar LLM traces. For each cluster, provide a short title and description that captures what makes traces in that cluster similar.

Having context about ALL clusters helps you create more distinctive and useful labels that differentiate between clusters.

Here are the {num_clusters} clusters with their representative traces:

"""

    for cluster in clusters_data:
        prompt += f"\n## Cluster {cluster['cluster_id']} ({cluster['size']} traces)\n\n"
        prompt += "Representative traces (closest to cluster center):\n\n"

        for i, trace in enumerate(cluster["representative_traces"], 1):
            prompt += f"### {i}. {trace.get('title', 'Untitled')}\n\n"

            if trace.get("flow_diagram"):
                prompt += f"**Flow:**\n```\n{trace['flow_diagram']}\n```\n\n"

            if trace.get("bullets"):
                prompt += f"**Summary:**\n{trace['bullets']}\n\n"

            if trace.get("interesting_notes"):
                prompt += f"**Notes:**\n{trace['interesting_notes']}\n\n"

            prompt += "---\n\n"

    prompt += """
Based on these representative traces, provide a title and description for each cluster:

1. **Title**: 3-10 words that capture the main pattern (e.g., "PDF Generation Errors", "Authentication Flows", "Data Pipeline Processing")
2. **Description**: 2-3 sentences explaining what traces in this cluster have in common in terms of similar usage patterns, error messages, functionality or anything that jumps out as interesting.

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
      "title": "Another Pattern explaining the cluster",
      "description": "What makes this cluster distinct from others."
    }
  ]
}

Make titles and descriptions distinctive - users need to quickly understand how clusters differ from each other.
"""
    return prompt


def _call_llm_for_labels(
    prompt: str,
    team_id: int,
    num_clusters: int,
    labels: np.ndarray,
) -> dict[int, ClusterLabel]:
    """Call OpenAI LLM to generate cluster labels.

    Args:
        prompt: The formatted prompt
        team_id: Team ID for tracking
        num_clusters: Number of clusters
        labels: Cluster assignments (for fallback labels)

    Returns:
        Dict mapping cluster_id -> ClusterLabel
    """
    # Validate environment
    if not settings.DEBUG and not is_cloud():
        raise Exception("AI features are only available in PostHog Cloud")

    if not os.environ.get("OPENAI_API_KEY"):
        raise Exception("OpenAI API key is not configured")

    # Create OpenAI client
    client = openai.OpenAI(
        timeout=LABELING_LLM_TIMEOUT,
        base_url=getattr(settings, "OPENAI_BASE_URL", None),
    )

    # Prepare user param for tracking
    instance_region = get_instance_region() or "HOBBY"
    user_param = f"{instance_region}/{team_id}"

    try:
        response = client.beta.chat.completions.parse(
            model=LABELING_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            user=user_param,
            response_format=ClusterLabelsResponse,
        )

        # Get parsed response
        result = response.choices[0].message.parsed
        if not result:
            raise Exception("OpenAI returned empty response")

        # Convert to dict[cluster_id -> ClusterLabel], validating cluster IDs
        valid_cluster_ids = set(range(num_clusters))
        labels_dict = {}
        for cluster in result.clusters:
            if cluster.cluster_id not in valid_cluster_ids:
                logger.warning(
                    "llm_returned_invalid_cluster_id",
                    cluster_id=cluster.cluster_id,
                    valid_ids=list(valid_cluster_ids),
                )
                continue
            labels_dict[cluster.cluster_id] = ClusterLabel(
                title=cluster.title,
                description=cluster.description,
            )

        # Fill in any missing clusters with fallback labels
        for cluster_id in valid_cluster_ids:
            if cluster_id not in labels_dict:
                logger.warning("llm_missing_cluster_label", cluster_id=cluster_id)
                labels_dict[cluster_id] = ClusterLabel(
                    title=f"Cluster {cluster_id}",
                    description=f"Cluster of {sum(1 for label in labels if label == cluster_id)} similar traces",
                )

        return labels_dict

    except Exception as e:
        logger.exception(
            "failed_to_generate_cluster_labels",
            error=str(e),
            error_type=type(e).__name__,
            team_id=team_id,
            num_clusters=num_clusters,
        )
        # Return fallback labels
        return {
            cluster_id: ClusterLabel(
                title=f"Cluster {cluster_id}",
                description=f"Cluster of {sum(1 for label in labels if label == cluster_id)} similar traces",
            )
            for cluster_id in range(num_clusters)
        }
