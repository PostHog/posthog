"""
Text representation formatters for AI observability events.

Pure Python implementation for formatting $ai_generation, $ai_span, and $ai_trace events
into human-readable text representations.

Main entry points:
- format_event_text_repr: Format single events ($ai_generation, $ai_span) from a
  `properties`-shaped event dict (e.g. an `events`-table row).
- format_event_text_repr_from_ai_events_row: Same, but for callers reading
  `posthog.ai_events` directly — accepts the dedicated-column shape and
  handles JSON decoding of heavy columns.
- format_trace_text_repr: Format full traces with hierarchy
- format_trace_text_repr_with_line_owners: Same, plus the event that rendered each line
- llm_trace_to_formatter_format: Convert LLMTrace to format_trace_text_repr input format
"""

from .event_formatter import format_event_text_repr, format_event_text_repr_from_ai_events_row
from .message_formatter import (
    EVENT_TEXT_MAX_CHARS,
    FormatterOptions,
    RenderBudgetExceeded,
    add_line_numbers,
    reduce_by_uniform_sampling,
    sanitize_surrogates,
    truncate_by_line_sampling,
)
from .trace_formatter import (
    TraceTextRepr,
    format_trace_text_repr,
    format_trace_text_repr_with_line_owners,
    llm_trace_to_formatter_format,
)

__all__ = [
    "EVENT_TEXT_MAX_CHARS",
    "FormatterOptions",
    "RenderBudgetExceeded",
    "TraceTextRepr",
    "add_line_numbers",
    "format_event_text_repr",
    "format_event_text_repr_from_ai_events_row",
    "format_trace_text_repr",
    "format_trace_text_repr_with_line_owners",
    "llm_trace_to_formatter_format",
    "reduce_by_uniform_sampling",
    "sanitize_surrogates",
    "truncate_by_line_sampling",
]
