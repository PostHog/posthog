"""
Activity 5 of the video segment clustering workflow:
Generating LLM-based labels for new clusters.
"""

import asyncio
from datetime import datetime

import structlog
from temporalio import activity

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.labeling import generate_cluster_labels_llm
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusterContext,
    ClusterLabel,
    GenerateLabelsActivityInputs,
    LabelingResult,
    VideoSegmentMetadata,
)

logger = structlog.get_logger(__name__)


def _calculate_metrics_from_segments(segments: list[VideoSegmentMetadata]) -> dict:
    """Calculate aggregate metrics from segment metadata."""
    if not segments:
        return {
            "distinct_user_count": 0,
            "occurrence_count": 0,
            "last_occurrence_at": None,
        }

    distinct_ids = {s.distinct_id for s in segments}
    distinct_user_count = len(distinct_ids)

    timestamps = []
    for s in segments:
        if s.timestamp:
            try:
                ts = datetime.fromisoformat(s.timestamp.replace("Z", "+00:00"))
                timestamps.append(ts)
            except ValueError:
                pass

    last_occurrence_at = max(timestamps) if timestamps else None

    return {
        "distinct_user_count": distinct_user_count,
        "occurrence_count": len(segments),
        "last_occurrence_at": last_occurrence_at,
    }


async def _generate_labels(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Generate LLM labels for clusters with actionability filtering."""
    segment_lookup = {s.document_id: s for s in inputs.segments}

    async def generate_label_for_cluster(cluster):
        """Generate label for a single cluster."""
        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]

        if not cluster_segments:
            return cluster.cluster_id, ClusterLabel(
                actionable=False,
                title="",
                description="",
            )

        metrics = _calculate_metrics_from_segments(cluster_segments)

        sample_segments = cluster_segments[: constants.DEFAULT_SEGMENTS_PER_CLUSTER_FOR_LABELING]

        context = ClusterContext(
            segment_contents=[s.content for s in sample_segments],
            distinct_user_count=metrics["distinct_user_count"],
            occurrence_count=metrics["occurrence_count"],
            last_occurrence_iso=metrics["last_occurrence_at"].isoformat() if metrics["last_occurrence_at"] else None,
        )

        try:
            label = await generate_cluster_labels_llm(
                team_id=inputs.team_id,
                context=context,
            )
            return cluster.cluster_id, label
        except Exception as e:
            logger.warning(
                "Failed to generate LLM label for cluster, marking not actionable",
                cluster_id=cluster.cluster_id,
                error=str(e),
            )
            return cluster.cluster_id, ClusterLabel(
                actionable=False,
                title="",
                description="",
            )

    results = await asyncio.gather(*[generate_label_for_cluster(cluster) for cluster in inputs.clusters])
    labels = dict(results)

    return LabelingResult(labels=labels)


@activity.defn
async def generate_labels_activity(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Generate LLM-based labels for new clusters, i.e. actionable task titles and descriptions."""
    return await _generate_labels(inputs)
