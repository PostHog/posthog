"""
Activity 4 of the video segment clustering workflow:
Label clusters with LLM, then emit each as a signal via emit_signal().
"""

import json
import math
import asyncio
from datetime import timedelta

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import types
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusterContext,
    ClusterLabel,
    EmitSignalsActivityInputs,
    EmitSignalsResult,
    VideoSegmentMetadata,
)
from posthog.temporal.ai.video_segment_clustering.priority import (
    calculate_task_metrics,
    parse_datetime_as_utc,
    parse_timestamp_to_seconds,
)

from products.signals.backend.api import emit_signal

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
- User error with no product fix (e.g., "User entered wrong password")

Mark as actionable if:
- Clear technical failure (errors, crashes, timeouts)
- Users repeatedly confused by UI/UX
- Workflow broken or blocked
- Multiple users hit same friction point

## Response format
If actionable: generate task title (5-10 words, starts with "Fix"/"Investigate"/"Improve") and description (1-3 sentences).
If not actionable: still return a brief title and description, but return actionable=False

Respond in JSON:
{
  "actionable": true/false,
  "title": "Your title",
  "description": "Your description"
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
async def emit_signals_from_clusters_activity(inputs: EmitSignalsActivityInputs) -> EmitSignalsResult:
    """Label clusters via LLM, calculate weights, and emit each as a signal."""
    team = await Team.objects.aget(id=inputs.team_id)
    segment_lookup = {s.document_id: s for s in inputs.segments}
    genai_client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)

    # 1. Label all clusters concurrently
    label_tasks = []
    for cluster in inputs.clusters:
        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]
        label_tasks.append(
            generate_label_for_cluster(
                team=team,
                cluster_id=cluster.cluster_id,
                cluster_segments=cluster_segments,
                genai_client=genai_client,
            )
        )
    label_results = await asyncio.gather(*label_tasks, return_exceptions=True)

    labels: dict[int, ClusterLabel] = {}
    for label_result in label_results:
        if isinstance(label_result, BaseException):
            logger.warning("Cluster labeling failed, skipping", error=str(label_result))
            continue
        cluster_id, label = label_result
        labels[cluster_id] = label

    # 2. Emit signals for each labeled cluster
    signals_emitted = 0
    clusters_skipped = 0

    for cluster in inputs.clusters:
        label = labels.get(cluster.cluster_id)
        if not label:
            clusters_skipped += 1
            continue

        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]
        if not cluster_segments:
            clusters_skipped += 1
            continue

        metrics = await calculate_task_metrics(team, cluster_segments)
        relevant_user_count = metrics["relevant_user_count"]

        # Weight: not-actionable = 0.1, actionable scales with user count
        if not label.actionable:
            weight = 0.1
        else:
            weight = min(0.5, 0.1 * math.log2(1 + relevant_user_count))

        # Build segment metadata for extra field
        segment_extras = []
        for seg in cluster_segments:
            session_start = parse_datetime_as_utc(seg.session_start_time)
            abs_start = session_start + timedelta(seconds=parse_timestamp_to_seconds(seg.start_time))
            abs_end = session_start + timedelta(seconds=parse_timestamp_to_seconds(seg.end_time))
            segment_extras.append(
                {
                    "session_id": seg.session_id,
                    "start_time": abs_start.isoformat(),
                    "end_time": abs_end.isoformat(),
                    "distinct_id": seg.distinct_id,
                    "content": seg.content,
                }
            )

        await emit_signal(
            team=team,
            source_product="session_recordings",
            source_type="segment_cluster",
            source_id=f"{team.id}:{inputs.workflow_run_id}:{cluster.cluster_id}",
            description=label.description,
            weight=weight,
            extra={
                "label_title": label.title,
                "actionable": label.actionable,
                "segments": segment_extras,
                "metrics": {
                    "relevant_user_count": relevant_user_count,
                    "occurrence_count": metrics["occurrence_count"],
                },
            },
        )
        signals_emitted += 1

        logger.info(
            "Emitted signal for cluster",
            cluster_id=cluster.cluster_id,
            cluster_size=cluster.size,
            actionable=label.actionable,
            weight=weight,
            relevant_user_count=relevant_user_count,
        )

    return EmitSignalsResult(signals_emitted=signals_emitted, clusters_skipped=clusters_skipped)


async def generate_label_for_cluster(
    *, team: Team, cluster_id: int, cluster_segments: list[VideoSegmentMetadata], genai_client
) -> tuple[int, ClusterLabel]:
    if not cluster_segments:
        raise ValueError("Cluster segments cannot be empty")

    distinct_ids = [s.distinct_id for s in cluster_segments if s.distinct_id]
    relevant_user_count = await sync_to_async(count_distinct_persons)(team, distinct_ids)

    last_occurrence_at = None
    for s in cluster_segments:
        session_start_time = parse_datetime_as_utc(s.session_start_time)
        segment_start_time = session_start_time + timedelta(seconds=parse_timestamp_to_seconds(s.start_time))
        if last_occurrence_at is None or segment_start_time > last_occurrence_at:
            last_occurrence_at = segment_start_time

    sample_segments = cluster_segments[: constants.DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING]

    context = ClusterContext(
        segment_contents=[s.content for s in sample_segments],
        relevant_user_count=relevant_user_count,
        occurrence_count=len(cluster_segments),
        last_occurrence_iso=last_occurrence_at.isoformat() if last_occurrence_at else None,
    )

    label = await _call_llm_to_label_cluster(context=context, genai_client=genai_client)
    return cluster_id, label


async def _call_llm_to_label_cluster(
    context: ClusterContext,
    genai_client,
    model: str = constants.LABELING_LLM_MODEL,
) -> ClusterLabel:
    if not context.segment_contents:
        raise ValueError("No segment contents provided")

    segment_texts = [f"{i}. {content}" for i, content in enumerate(context.segment_contents, 1)]
    user_prompt = LABELING_USER_PROMPT_TEMPLATE.format(
        sample_count=len(context.segment_contents),
        segment_texts_joined="\n".join(segment_texts),
        relevant_user_count=context.relevant_user_count,
        occurrence_count=context.occurrence_count,
        last_occurrence_iso=context.last_occurrence_iso or "Unknown",
    )

    prompt_parts = [
        types.Part(text=LABELING_SYSTEM_PROMPT),
        types.Part(text=user_prompt),
    ]

    for attempt in range(3):
        try:
            response = await genai_client.models.generate_content(
                model=model,
                contents=prompt_parts,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=ClusterLabel.model_json_schema(),
                ),
            )
            content = response.text
            if not content:
                raise ValueError("Empty response from LLM")
            result = json.loads(content)
            title = result["title"]
            description = result["description"]
            assert title and description, "Title and description must be non-empty"
            return ClusterLabel(
                actionable=result["actionable"],
                title=title,
                description=description,
            )
        except Exception as e:
            if attempt == 2:
                raise
            prompt_parts.append(
                types.Part(text=f"\n\nAttempt {attempt + 1} failed with error: {e!r}\nPlease fix your output.")
            )

    raise RuntimeError("Unreachable")
