"""
Activity 4 of the video-based summarization workflow:
Consolidating raw video segments into meaningful semantic segments using LLM.
(Python modules have to start with a letter, hence the file is prefixed `a4_` instead of `4_`.)
"""

import json

from django.conf import settings

import structlog
import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    VideoSegmentOutput,
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
        logger.debug(
            f"Consolidating {len(raw_segments)} raw segments for session {inputs.session_id}",
            session_id=inputs.session_id,
            raw_segment_count=len(raw_segments),
            signals_type="session-summaries",
        )
        segments_text = "\n".join(f"- **{seg.start_time} - {seg.end_time}:** {seg.description}" for seg in raw_segments)

        # Generate JSON schema from Pydantic model
        json_schema = ConsolidatedVideoAnalysis.model_json_schema()
        json_schema_str = json.dumps(json_schema)

        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)

        prompt_parts = [
            types.Part(text=CONSOLIDATION_PROMPT.format(segments_text=segments_text, json_schema=json_schema_str)),
        ]

        consolidated_analysis = await _call_llm_to_consolidate_segments(
            client=client,
            prompt_parts=prompt_parts,
            inputs=inputs,
            trace_id=trace_id,
        )

        logger.debug(
            f"Consolidated {len(raw_segments)} raw segments into {len(consolidated_analysis.segments)} semantic segments",
            session_id=inputs.session_id,
            raw_count=len(raw_segments),
            consolidated_count=len(consolidated_analysis.segments),
            session_success=consolidated_analysis.session_outcome.success,
            signals_type="session-summaries",
        )

        return consolidated_analysis

    except Exception:
        logger.exception(
            f"Failed to consolidate segments for session {inputs.session_id}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        # Re-raise to let the workflow retry with proper retry policy
        raise


async def _call_llm_to_consolidate_segments(
    *,
    client,
    prompt_parts: list[types.Part],
    inputs: VideoSummarySingleSessionInputs,
    trace_id: str,
    max_attempts: int = 3,
) -> ConsolidatedVideoAnalysis:
    """Call LLM to consolidate segments, with retry and error feedback."""
    for attempt in range(max_attempts):
        try:
            response = await client.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=prompt_parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=ConsolidatedVideoAnalysis.model_json_schema(),
                ),
                posthog_distinct_id=inputs.user_distinct_id_to_log,
                posthog_trace_id=trace_id,
                posthog_properties={"$session_id": inputs.session_id},
                posthog_groups={"project": str(inputs.team_id)},
            )

            response_text = response.text
            if not response_text:
                raise ValueError("Empty response from LLM")

            parsed = json.loads(response_text)
            return ConsolidatedVideoAnalysis.model_validate(parsed)

        except Exception as e:
            if attempt == max_attempts - 1:
                logger.exception(
                    f"Failed to parse/validate LLM response after {max_attempts} attempts",
                    session_id=inputs.session_id,
                    last_error=repr(e),
                    signals_type="session-summaries",
                )
                raise
            prompt_parts.append(
                types.Part(text=f"\n\nAttempt {attempt + 1} failed with error: {e!r}\nPlease fix your output.")
            )

    # Should never reach here, but satisfy type checker
    raise RuntimeError("Unreachable")


CONSOLIDATION_PROMPT = """
You are summarizing a user's journey through a product session for PMs, developers, and analysts who want to understand what the user did and whether anything needs attention.

Below are timestamped observations. Produce a short narrative summary + key moments.

Session outcome:
- 1-2 sentence TLDR: where the user went, what they did, and how it ended. Scannable — a PM should know whether to watch this session in 5 seconds.
- Good: "Explored analytics dashboard, created a funnel, and shared results. Hit a validation error during project setup but moved on."
- Bad: "Encountered persistent loading failures that prevented effective analysis."

Each segment is a key moment in the session:
- **Title**: What happened in this moment (e.g., "Opened funnel creation", "Hit validation error on project setup", "Completed onboarding"). Sentence-cased. Specific, not generic.
- **Description**: 1 sentence — the key action and its result. Keep it tight. Describe what happened at face value — don't amplify or dramatize severity.
  - Good: "Filled out the project form and hit a 'Name is required' error."
  - Bad: "The user proceeded to fill out the project creation form, entering various fields including the name and description, and then clicked the submit button, which resulted in a validation error message appearing on screen."
- **Success**: Did the user finish what they were doing?
- **Flags**: exception="blocking" only if it visibly stopped the user. confusion/abandonment only when clearly observed.

Segmentation:
- Each segment is a meaningful chunk of activity, not a single action. A chunk covers the full flow: navigating to a feature, using it, and the outcome. Example: "Went to Feature Flags, created a new flag, got blocked by unresponsive dropdown" is ONE segment, not three.
- Short sessions: 1-3 segments. Long sessions: 3-6. If you have more than 6, you are fragmenting too much — merge harder.
- Merge all activity in the same area/feature into one segment, even if some actions succeeded and others failed. Example: browsing recordings, trying to load summaries, checking event details — if it all happened on the same page within a few minutes, that's ONE segment.
- Merge repeated attempts at the same thing into one segment. If the user spent most of the session hitting the same issue, keep segments minimal and let fix_suggestions carry the detail.
- Segments are chronological. Users often pivot between goals within a session — group related actions into arcs, but don't force unrelated activity into one narrative. Example: "Dashboard exploration" → "Feature flag creation" can be two separate arcs if the user switched context.
- Stick to what you can observe; do not infer motivation or intent.

fix_suggestions:
- Error details belong here, not in segment descriptions. Do not repeat error messages or specific failure details in both places.
- Segment descriptions should mention that something failed; fix_suggestions should say exactly what error appeared and what to do about it.
- Each needs: issue, evidence (exact error or observed behavior), suggestion.
- Only include when grounded in something specific. Empty list is fine.

Raw segments:
{segments_text}

Output a JSON object matching this schema, no other text:
```json
{json_schema}
```

Style:
- Be direct. No filler ("The user proceeded to", "It was observed that").
- Vary phrasing — don't start every sentence with "The user".
- Preserve specific feature names, page names, and error messages.

Rules:
- Time ranges must not overlap and should cover the full session.
- One segment_outcome per segment with a brief narrative summary.
"""
