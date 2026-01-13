"""LLM-based cluster labeling for video segment clustering."""

import json

from django.conf import settings

import structlog
from google.genai import types
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import ClusterContext, ClusterLabel

logger = structlog.get_logger(__name__)


LABELING_SYSTEM_PROMPT = """You are an expert at analyzing user behavior patterns from session replay video analysis.

Given video segment descriptions grouped as similar issues, along with impact metrics,
determine if this cluster represents an actionable issue for an engineering team.

## Context provided
- Segment descriptions: What users experienced (up to 5 examples)
- Impact flags per segment: failure_detected, confusion_detected, abandonment_detected
- Aggregate impact score: 0-1 (higher = more impactful)
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


async def generate_cluster_labels_llm(
    team_id: int,
    context: ClusterContext,
    model: str = constants.LABELING_LLM_MODEL,
) -> ClusterLabel:
    """Generate a label for a cluster using LLM, including actionability check.

    Args:
        team_id: Team ID for logging
        context: ClusterContext with segments, impact data, and metrics
        model: LLM model to use

    Returns:
        ClusterLabel with actionable flag and optional title/description
    """
    if not context.segment_contents:
        return ClusterLabel(
            actionable=False,
            title="",
            description="",
        )

    # Build prompt with full context
    segment_texts = []
    for i, (content, flags) in enumerate(zip(context.segment_contents, context.segment_impact_flags), 1):
        flag_strs = []
        if flags.get("failure_detected"):
            flag_strs.append("failure")
        if flags.get("confusion_detected"):
            flag_strs.append("confusion")
        if flags.get("abandonment_detected"):
            flag_strs.append("abandonment")
        flag_info = f" [Impact: {', '.join(flag_strs)}]" if flag_strs else ""
        segment_texts.append(f"{i}. {content}{flag_info}")

    user_prompt = f"""Cluster analysis:

## Segment descriptions ({len(context.segment_contents)} samples):
{chr(10).join(segment_texts)}

## Metrics:
- Aggregate impact score: {context.aggregate_impact_score:.2f}
- Distinct users affected: {context.distinct_user_count}
- Total occurrences: {context.occurrence_count}
- Last occurred: {context.last_occurrence_iso or 'Unknown'}

Determine if this cluster is actionable and generate task details if so."""

    try:
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model=model,
            contents=[types.Part(text=LABELING_SYSTEM_PROMPT), types.Part(text=user_prompt)],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=ClusterLabel.model_json_schema(),
            ),
        )

        content = response.text
        if not content:
            raise ValueError("Empty response from LLM")

        result = json.loads(content)
        is_actionable = result.get("actionable", False)

        return ClusterLabel(
            actionable=is_actionable,
            title=result.get("title", "")[:255] if is_actionable else "",
            description=result.get("description", "")[:2000] if is_actionable else "",
        )

    except Exception as e:
        logger.warning(
            "LLM labeling failed, marking as not actionable",
            team_id=team_id,
            error=str(e),
        )

        return ClusterLabel(
            actionable=False,
            title="",
            description="",
        )
