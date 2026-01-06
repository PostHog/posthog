"""
Activity 4 of the video-based summarization workflow:
Consolidating raw video segments into meaningful semantic segments using LLM.
(Python modules have to start with a letter, hence the file is prefixed `a4_` instead of `4_`.)
"""

import re
import json

from django.conf import settings

import structlog
import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    VideoSegmentOutput,
    VideoSessionOutcome,
    VideoSummarySingleSessionInputs,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def consolidate_video_segments_activity(
    inputs: VideoSummarySingleSessionInputs,
    raw_segments: list[VideoSegmentOutput],
    trace_id: str,
) -> ConsolidatedVideoAnalysis:
    """Consolidate raw video segments into meaningful semantic segments using LLM.

    Takes the raw segments from video analysis (which have generic timestamps but no meaningful titles)
    and asks an LLM to reorganize them into semantically meaningful segments with proper titles,
    along with session-level and segment-level outcomes.

    This preserves all information while creating logical groupings like:
    - "User onboarding flow"
    - "Debugging API configuration"
    - "Exploring dashboard features"

    Also detects:
    - Success/failure of the overall session
    - Per-segment outcomes (success, confusion, abandonment, failures)
    """
    if not raw_segments:
        raise ApplicationError(
            f"No segments extracted from video analysis for session {inputs.session_id}. "
            "All video segments may have been static or the LLM output format was not parseable.",
            non_retryable=True,
        )

    try:
        logger.info(
            f"Consolidating {len(raw_segments)} raw segments for session {inputs.session_id}",
            session_id=inputs.session_id,
            raw_segment_count=len(raw_segments),
        )
        segments_text = "\n".join(f"- **{seg.start_time} - {seg.end_time}:** {seg.description}" for seg in raw_segments)
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[
                CONSOLIDATION_PROMPT.format(
                    segments_text=segments_text, example_json=json.dumps(CONSOLIDATION_PROMPT_EXAMPLE_JSON, indent=2)
                )
            ],
            config=types.GenerateContentConfig(max_output_tokens=8192),
            posthog_distinct_id=inputs.user_distinct_id_to_log,
            posthog_trace_id=trace_id,
            posthog_properties={"$session_id": inputs.session_id},
            posthog_groups={"project": str(inputs.team_id)},
        )

        response_text = (response.text or "").strip()

        # Extract JSON from response (handle potential Markdown code block)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text

        parsed = json.loads(json_str)

        # Parse segments
        consolidated_segments = [
            ConsolidatedVideoSegment(
                title=item["title"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                description=item["description"],
                success=item.get("success", True),
                failure_detected=item.get("failure_detected", False),
                confusion_detected=item.get("confusion_detected", False),
                abandonment_detected=item.get("abandonment_detected", False),
            )
            for item in (parsed.get("segments") or [])
        ]

        # Parse session outcome
        session_outcome_data = parsed.get("session_outcome", {})
        session_outcome = VideoSessionOutcome(
            success=session_outcome_data.get("success", True),
            description=session_outcome_data.get("description", "Session analyzed via video"),
        )

        # Parse segment outcomes
        segment_outcomes = parsed.get("segment_outcomes", [])

        logger.info(
            f"Consolidated {len(raw_segments)} raw segments into {len(consolidated_segments)} semantic segments",
            session_id=inputs.session_id,
            raw_count=len(raw_segments),
            consolidated_count=len(consolidated_segments),
            session_success=session_outcome.success,
        )

        return ConsolidatedVideoAnalysis(
            segments=consolidated_segments,
            session_outcome=session_outcome,
            segment_outcomes=segment_outcomes,
        )

    except Exception as e:
        logger.exception(
            f"Failed to consolidate segments for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        # Re-raise to let the workflow retry with proper retry policy
        raise


CONSOLIDATION_PROMPT = """
You are analyzing a session recording from a web analytics product. Below are timestamped descriptions of what the user did during the session.

Your task is to consolidate these into meaningful semantic segments and provide an overall analysis. For each segment:
1. Have a **descriptive title** that captures the user's goal or activity (e.g., "Setting up integration", "Exploring analytics dashboard", "Debugging API errors")
2. Span a coherent period of related activity (combine adjacent segments that are part of the same task)
3. Have a **combined description** that synthesizes the details from the original segments
4. Detect if the user experienced **failures** (errors, things not working), **confusion** (backtracking, hesitation, repeated attempts), or **abandonment** (starting something but not finishing)
5. Determine if the segment was **successful** (user achieved their apparent goal)

Raw segments:
{segments_text}

Output format (JSON object):
```json
{example_json}
```

Rules:
- Create as many segments as needed depending on session complexity (fewer for short simple sessions, more for long complex ones)
- Titles should be specific (avoid generic titles like "User activity" or "Browsing")
- Titles must be sentence-cased (capitalize only the first letter and proper nouns)
- Time ranges must not overlap and should cover the full session
- Preserve error messages, specific UI elements clicked, and outcomes mentioned in original segments
- Keep descriptions concise but complete
- Set failure_detected=true if you see error messages, failed actions, or things not working as expected
- Set confusion_detected=true if the user backtracks, hesitates, or makes repeated attempts at the same thing
- Set abandonment_detected=true if the user starts a flow but doesn't complete it
- Set success=false for segments where the user's apparent goal wasn't achieved
- session_outcome.success should be true if the user accomplished their main goals, false if they left frustrated or unsuccessful
- segment_outcomes should have one entry per segment with a brief summary of what happened

Output ONLY the JSON object, no other text.
"""
CONSOLIDATION_PROMPT_EXAMPLE_JSON = {
    "segments": [
        {
            "title": "Descriptive segment title",
            "start_time": "MM:SS",
            "end_time": "MM:SS",
            "description": "Combined description of what happened in this segment",
            "success": True,
            "failure_detected": False,
            "confusion_detected": False,
            "abandonment_detected": False,
        }
    ],
    "session_outcome": {
        "success": True,
        "description": "Overall summary of session outcome - what the user accomplished or failed to accomplish",
    },
    "segment_outcomes": [
        {
            "segment_index": 0,
            "success": True,
            "summary": "Brief summary of segment outcome",
        }
    ],
}
