from pathlib import Path
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SessionSummaryPrompt
from ee.session_recordings.session_summary.utils import load_custom_template


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
