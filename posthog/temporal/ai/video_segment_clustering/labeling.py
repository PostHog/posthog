"""LLM-based cluster labeling for video segment clustering."""

import json

from django.conf import settings

import structlog
from google.genai import types
from google.genai.types import GenerateContentConfig
from posthoganalytics.ai.gemini import genai

from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import ClusterLabel, VideoSegment

logger = structlog.get_logger(__name__)


LABELING_SYSTEM_PROMPT = """You are an expert at analyzing user behavior patterns from session replay video analysis.

Given a set of video segment descriptions that have been grouped together as similar issues,
generate a concise, actionable task title and description for an engineering team.

The title should:
- Be 5-10 words max
- Describe the core issue or pattern
- Be actionable (start with a verb like "Fix", "Investigate", "Improve")

The description should:
- Be 1-3 sentences
- Explain what users are experiencing
- Suggest what might be causing the issue
- Be written for engineers who need to fix the problem

Respond in JSON format:
{
  "title": "Your title here",
  "description": "Your description here"
}
"""


async def generate_cluster_labels_llm(
    team_id: int,
    segments: list[VideoSegment],
    model: str = constants.LABELING_LLM_MODEL,
) -> ClusterLabel:
    """Generate a label for a cluster using LLM.

    Args:
        team_id: Team ID for logging
        segments: Representative segments from the cluster
        model: LLM model to use
        timeout: Request timeout in seconds

    Returns:
        ClusterLabel with title and description
    """

    if not segments:
        return ClusterLabel(
            title="Unknown Issue",
            description="No segment data available.",
        )

    # Build prompt with segment contents
    segment_texts = []
    for i, segment in enumerate(segments, 1):
        segment_texts.append(f"{i}. {segment.content}")

    user_prompt = f"""Here are {len(segments)} video segment descriptions from user sessions that have been grouped as similar issues:

{chr(10).join(segment_texts)}

Generate a task title and description for fixing this issue."""

    try:
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model=model,
            contents=[types.Part(text=LABELING_SYSTEM_PROMPT), types.Part(text=user_prompt)],
            config=GenerateContentConfig(
                response_mime_type="application/json", response_json_schema=ClusterLabel.model_json_schema()
            ),
            temperature=0,
        )

        content = response.text
        if not content:
            raise ValueError("Empty response from LLM")

        result = json.loads(content)

        return ClusterLabel(
            title=result.get("title", "Unknown Issue")[:255],
            description=result.get("description", "")[:2000],
        )

    except Exception as e:
        logger.warning(
            "LLM labeling failed, using fallback",
            team_id=team_id,
            error=str(e),
        )

        # Fallback: Use first segment content
        first_segment = segments[0]
        title = first_segment.content[:50]
        if len(first_segment.content) > 50:
            title += "..."

        return ClusterLabel(
            title=f"Issue: {title}",
            description=first_segment.content[:500],
        )
