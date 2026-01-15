"""
Activity 5 of the video segment clustering workflow:
Generating LLM-based labels for new clusters.
"""

import json
import asyncio
from datetime import datetime, timedelta

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import types
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from temporalio import activity

from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment import _parse_timestamp_to_seconds
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusterContext,
    ClusterLabel,
    LabelClustersActivityInputs,
    LabelingResult,
    VideoSegmentMetadata,
)

logger = structlog.get_logger(__name__)


LABELING_SYSTEM_PROMPT = """You are an expert at analyzing user behavior patterns from session replay video analysis.

Given video segment descriptions grouped as similar issues, determine if this cluster represents an actionable issue for an engineering team.

## Context provided
- Segment descriptions: What users experienced (up to 5 examples)
- Distinct user count: Unique users affected
- Occurrence count: Total occurrences
- Last occurrence: When last seen

## Actionability criteria
Mark as NOT actionable if:
- Normal, expected user behavior (e.g., "User browsed products")
- Feature request rather than bug/friction (e.g., "User looked for dark mode")
- Too vague to act on (e.g., "Something went wrong")
- User error with no product fix (e.g., "User entered wrong password")

Mark as actionable if:
- Clear technical failure (errors, crashes, timeouts)
- Users repeatedly confused by UI/UX
- Workflow broken or blocked
- Multiple users hit same friction point

## Response format
If actionable: generate task title (5-10 words, starts with "Fix"/"Investigate"/"Improve") and description (1-3 sentences).
If not actionable: return empty title and description.

Respond in JSON:
{
  "actionable": true/false,
  "title": "Your title or empty string",
  "description": "Your description or empty string"
}
"""

LABELING_USER_PROMPT_TEMPLATE = """Cluster analysis:

## Segment descriptions ({sample_count} samples):
{segment_texts_joined}

## Metrics:
- Distinct users affected: {relevant_user_count}
- Total occurrences: {occurrence_count}
- Last occurred: {last_occurrence_iso}

Determine if this cluster is actionable and generate task details if so."""


@activity.defn
async def label_clusters_activity(inputs: LabelClustersActivityInputs) -> LabelingResult:
    """
    Filter out non-actionable clusters.
    For the actionable clusters, generate labels, i.e. actionable task titles and descriptions.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    segment_lookup = {s.document_id: s for s in inputs.segments}
    result = await asyncio.gather(
        *[
            generate_label_for_cluster(
                team=team,
                cluster_id=cluster.cluster_id,
                cluster_segments=[segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup],
            )
            for cluster in inputs.clusters
        ]
    )
    return LabelingResult(labels=dict(result))


async def generate_label_for_cluster(
    *, team: Team, cluster_id: int, cluster_segments: list[VideoSegmentMetadata]
) -> tuple[int, ClusterLabel]:
    if not cluster_segments:
        # This should not happen, but you never know...
        return cluster_id, ClusterLabel(
            actionable=False,
            title="",
            description="",
        )

    metrics = await _calculate_metrics_from_segments(team, cluster_segments)

    sample_segments = cluster_segments[: constants.DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING]

    context = ClusterContext(
        segment_contents=[s.content for s in sample_segments],
        relevant_user_count=metrics["relevant_user_count"],
        occurrence_count=metrics["occurrence_count"],
        last_occurrence_iso=metrics["last_occurrence_at"].isoformat() if metrics["last_occurrence_at"] else None,
    )

    try:
        label = await _call_llm_to_label_cluster(
            context=context,
        )
        return cluster_id, label
    except:
        logger.exception(
            "Failed to generate LLM label for cluster, marking not actionable",
            cluster_id=cluster_id,
        )
        return cluster_id, ClusterLabel(
            actionable=False,
            title="",
            description="",
        )


async def _calculate_metrics_from_segments(team: Team, segments: list[VideoSegmentMetadata]) -> dict:
    if not segments:
        return {
            "relevant_user_count": 0,
            "occurrence_count": 0,
            "last_occurrence_at": None,
        }

    # Count unique persons via SQL (a person can have multiple distinct_ids)
    distinct_ids = [s.distinct_id for s in segments if s.distinct_id]
    relevant_user_count = await sync_to_async(count_distinct_persons)(team, distinct_ids)

    last_occurrence_at = None
    for s in segments:
        session_start_time = datetime.fromisoformat(s.session_start_time.replace("Z", "+00:00"))
        segment_start_time = session_start_time + timedelta(seconds=_parse_timestamp_to_seconds(s.start_time))
        if last_occurrence_at is None or segment_start_time > last_occurrence_at:
            last_occurrence_at = segment_start_time

    return {
        "relevant_user_count": relevant_user_count,
        "occurrence_count": len(segments),
        "last_occurrence_at": last_occurrence_at,
    }


async def _call_llm_to_label_cluster(
    context: ClusterContext,
    model: str = constants.LABELING_LLM_MODEL,
) -> ClusterLabel:
    """Generate a label for a cluster using LLM, including actionability check."""
    if not context.segment_contents:
        return ClusterLabel(
            actionable=False,
            title="",
            description="",
        )

    # Build prompt with full context
    segment_texts = [f"{i}. {content}" for i, content in enumerate(context.segment_contents, 1)]

    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    response = await client.models.generate_content(
        model=model,
        contents=[
            types.Part(text=LABELING_SYSTEM_PROMPT),
            types.Part(
                text=LABELING_USER_PROMPT_TEMPLATE.format(
                    sample_count=len(context.segment_contents),
                    segment_texts_joined="\n".join(segment_texts),
                    relevant_user_count=context.relevant_user_count,
                    occurrence_count=context.occurrence_count,
                    last_occurrence_iso=context.last_occurrence_iso or "Unknown",
                )
            ),
        ],
        config=GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=ClusterLabel.model_json_schema(),
        ),
    )
    content = response.text
    if not content:
        raise ValueError("Empty response from LLM")
    result = json.loads(content)
    return ClusterLabel(
        actionable=result.get("actionable", False),
        title=result.get("title", ""),
        description=result.get("description", ""),
    )
