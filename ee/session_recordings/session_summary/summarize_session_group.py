import json
from pathlib import Path
from ee.session_recordings.session_summary.output_data import IntermediateSessionSummarySerializer
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, PatternsExtractionPrompt, SessionSummaryPrompt
from ee.session_recordings.session_summary.utils import load_custom_template


def remove_excessive_content_from_session_summary_for_llm(session_summary_str: str) -> str:
    """Remove excessive content from session summary for LLM when using for group summaries"""
    session_summary = IntermediateSessionSummarySerializer(data=json.loads(session_summary_str))
    if not session_summary.is_valid():
        raise ValueError(
            f"Caught invalid session summary when removing excessive content for group summaries ({session_summary.errors}): {session_summary_str}"
        )
    return json.dumps(session_summary.data)


def generate_session_group_summary_prompt(
    session_summaries: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> SessionSummaryPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()
    combined_session_summaries = "\n\n".join(session_summaries)
    # Render all templates
    template_dir = Path(__file__).parent / "templates" / "session-group-summary"
    system_prompt = load_custom_template(
        template_dir,
        "system-prompt.djt",
        {
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    summary_example = load_custom_template(template_dir, f"example.md")
    summary_prompt = load_custom_template(
        template_dir,
        f"prompt.djt",
        {
            "SESSION_SUMMARIES": combined_session_summaries,
            "SUMMARY_EXAMPLE": summary_example,
            "FOCUS_AREA": extra_summary_context.focus_area,
        },
    )
    return SessionSummaryPrompt(
        summary_prompt=summary_prompt,
        system_prompt=system_prompt,
    )


def generate_session_group_patterns_extraction_prompt(
    session_summaries: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> SessionSummaryPrompt:
    if extra_summary_context is None:
        extra_summary_context = ExtraSummaryContext()
    combined_session_summaries = "\n\n".join(session_summaries)
    template_dir = Path(__file__).parent / "templates" / "session-group-summary" / "patterns"
    system_prompt = load_custom_template(template_dir, "system-prompt.djt")
    patterns_example = load_custom_template(template_dir, f"example.yml")
    patterns_prompt = load_custom_template(
        template_dir,
        f"prompt.djt",
        {
            "SESSION_SUMMARIES": combined_session_summaries,
            "PATTERNS_EXAMPLE": patterns_example,
            # TODO: Add focus area to the prompt
        },
    )
    return PatternsExtractionPrompt(
        patterns_prompt=patterns_prompt,
        system_prompt=system_prompt,
    )