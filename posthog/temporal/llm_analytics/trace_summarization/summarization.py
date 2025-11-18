"""Activity for generating trace summaries using LLM."""

from typing import Any

import temporalio

from posthog.temporal.llm_analytics.trace_summarization.models import TraceSummary


@temporalio.activity.defn
async def generate_summary_activity(
    trace_data: dict[str, Any],
    team_id: int,
    mode: str,
    model: str | None = None,
) -> TraceSummary:
    """
    Generate text repr and summary for a single trace.

    Uses the existing summarization infrastructure from the API.
    """
    from products.llm_analytics.backend.summarization.llm import summarize
    from products.llm_analytics.backend.text_repr.formatters import FormatterOptions, format_trace_text_repr

    trace = trace_data["trace"]
    hierarchy = trace_data["hierarchy"]
    trace_id = trace["properties"]["$ai_trace_id"]

    # Generate text representation
    options: FormatterOptions = {
        "include_line_numbers": True,
        "truncated": False,
        "include_markers": False,
        "collapsed": False,
    }

    text_repr = format_trace_text_repr(
        trace=trace,
        hierarchy=hierarchy,
        options=options,
    )

    # Generate summary using LLM
    summary_result = await summarize(
        text_repr=text_repr,
        team_id=team_id,
        trace_id=trace_id,
        mode=mode,
        model=model,
    )

    return TraceSummary(
        trace_id=trace_id,
        text_repr=text_repr,
        summary=summary_result,  # Keep as SummarizationResponse for type safety
        metadata={
            "text_repr_length": len(text_repr),
            "mode": mode,
            "event_count": len(hierarchy),
        },
    )
