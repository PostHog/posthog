from datetime import datetime
from pathlib import Path
from typing import Any

from rest_framework import exceptions

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from ee.hogai.session_summaries.session.output_data import IntermediateSessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext, PatternsPrompt
from ee.hogai.session_summaries.session_group.patterns import RawSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.utils import load_custom_template


def remove_excessive_content_from_session_summary_for_llm(
    session_summary_dict: dict[str, Any],
) -> IntermediateSessionSummarySerializer:
    """Remove excessive content from session summary for LLM when using for group summaries"""
    session_summary = IntermediateSessionSummarySerializer(data=session_summary_dict)
    if not session_summary.is_valid():
        raise ValueError(
            f"Caught invalid session summary when removing excessive content for group summaries ({session_summary.errors}): {session_summary_dict}"
        )
    return session_summary


def generate_session_group_patterns_extraction_prompt(
    session_summaries_str: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()
    combined_session_summaries = "\n\n".join(session_summaries_str)
    template_dir = Path(__file__).parent / "templates" / "patterns_extraction"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "SESSION_SUMMARIES": combined_session_summaries,
            "PATTERNS_EXTRACTION_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(
        patterns_prompt=patterns_prompt,
        system_prompt=system_prompt,
    )


def generate_session_group_patterns_assignment_prompt(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_str: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()
    combined_session_summaries = "\n\n".join(session_summaries_str)
    template_dir = Path(__file__).parent / "templates" / "patterns_assignment"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "PATTERNS": patterns.model_dump_json(exclude_none=True),
            "SESSION_SUMMARIES": combined_session_summaries,
            "PATTERNS_ASSIGNMENT_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(
        patterns_prompt=patterns_prompt,
        system_prompt=system_prompt,
    )


def generate_session_group_patterns_combination_prompt(
    patterns_chunks: list[RawSessionGroupSummaryPatternsList],
    extra_summary_context: ExtraSummaryContext | None,
) -> PatternsPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()

    # Serialize all the pattern chunks to inject into the prompt
    patterns_chunks_yaml = []
    for i, chunk in enumerate(patterns_chunks):
        patterns_chunks_yaml.append(f"Patterns chunk #{i+1}:\n\n{chunk.model_dump_json(exclude_none=True)}")
    combined_patterns_chunks = "\n\n---\n\n".join(patterns_chunks_yaml)

    # Render templates
    template_dir = Path(__file__).parent / "templates" / "patterns_combining"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, "example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        "prompt.djt",
        {
            "PATTERNS_CHUNKS": combined_patterns_chunks,
            "PATTERNS_COMBINING_EXAMPLE": patterns_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return PatternsPrompt(
        patterns_prompt=patterns_prompt,
        system_prompt=system_prompt,
    )


def find_sessions_timestamps(session_ids: list[str], team: Team) -> tuple[datetime, datetime]:
    """Validate that all session IDs exist and belong to the team and return min/max timestamps for the entire list of sessions"""
    replay_events = SessionReplayEvents()
    sessions_found, min_timestamp, max_timestamp = replay_events.sessions_found_with_timestamps(session_ids, team)
    # Check for missing sessions
    if len(sessions_found) != len(session_ids):
        missing_sessions = set(session_ids) - sessions_found
        raise exceptions.ValidationError(
            f"Sessions not found or do not belong to this team: {', '.join(missing_sessions)}"
        )
    # Check for missing timestamps
    if min_timestamp is None or max_timestamp is None:
        raise exceptions.ValidationError(
            f"Failed to get min ({min_timestamp}) or max ({max_timestamp}) timestamps for sessions: {', '.join(session_ids)}"
        )
    return min_timestamp, max_timestamp
