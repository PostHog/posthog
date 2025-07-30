import json
from pathlib import Path
from ee.hogai.session_summaries.session.output_data import IntermediateSessionSummarySerializer
from ee.hogai.session_summaries.session_group.patterns import RawSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session.summarize_session import (
    ExtraSummaryContext,
    PatternsPrompt,
    SessionSummaryPrompt,
)
from ee.hogai.session_summaries.utils import load_custom_template


def remove_excessive_content_from_session_summary_for_llm(
    session_summary_str: str,
) -> IntermediateSessionSummarySerializer:
    """Remove excessive content from session summary for LLM when using for group summaries"""
    session_summary = IntermediateSessionSummarySerializer(data=json.loads(session_summary_str))
    if not session_summary.is_valid():
        raise ValueError(
            f"Caught invalid session summary when removing excessive content for group summaries ({session_summary.errors}): {session_summary_str}"
        )
    return session_summary


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
        "prompt.djt",
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
