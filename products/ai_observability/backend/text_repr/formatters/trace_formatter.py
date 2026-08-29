"""
Format full traces with hierarchy for text view.

Creates ASCII tree structure with clickable expandable nodes for trace visualization.
Handles hierarchical event relationships, trace-level input/output state, and
supports both interactive frontend markers and plain text for backend/LLM consumption.
"""

import json
import base64
from typing import Any

from dateutil.parser import isoparse

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.dataclasses import frozen

from .constants import DEFAULT_MAX_LENGTH, MAX_TREE_DEPTH, SEPARATOR
from .event_formatter import format_event_text_repr
from .message_formatter import (
    FormatterOptions,
    add_line_numbers,
    format_input_messages,
    format_output_messages,
    reduce_by_uniform_sampling,
    truncate_content,
)

# Annotations the trace view attaches to other nodes rather than rendering as steps of its own.
FEEDBACK_EVENT_TYPES = frozenset({"$ai_feedback", "$ai_metric"})


@frozen(order=True)
class _TraceEventSortKey:
    operation_start_ms: float
    negative_latency_ms: float


def _first_set_property(properties: dict[str, Any], *keys: str) -> Any:
    """First of `keys` that is set, mirroring the `??` chains the trace view resolves IDs with."""
    for key in keys:
        value = properties.get(key)
        if value is not None:
            return value
    return None


def _normalize_hierarchy_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str | int | float):
        return str(value)
    return None


def _latency_ms(event: LLMTraceEvent) -> float:
    try:
        latency = float(event.properties.get("$ai_latency", 0))
    except (TypeError, ValueError):
        return 0.0
    return latency * 1000 if latency > 0 else 0.0


def _operation_start_ms(event: LLMTraceEvent) -> float:
    """Epoch ms the event's operation began. PostHog AI SDKs capture an event when the operation
    finishes, so its timestamp is the end; OTel-ingested spans already carry the start."""
    try:
        end_ms = isoparse(event.createdAt).timestamp() * 1000
    except (TypeError, ValueError):
        return 0.0
    if event.properties.get("$ai_ingestion_source") == "otel":
        return end_ms
    return end_ms - _latency_ms(event)


def _to_formatter_event(event: LLMTraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event": event.event,
        "properties": event.properties,
        "timestamp": event.createdAt,
    }


def _nest_events(llm_trace: LLMTrace) -> list[dict[str, Any]]:
    """Rebuild the parent/child hierarchy the trace view shows, following `$ai_parent_id` links."""
    events_by_node_id: dict[str, LLMTraceEvent] = {}

    for event in llm_trace.events:
        if event.event in FEEDBACK_EVENT_TYPES:
            continue
        node_id = _normalize_hierarchy_id(_first_set_property(event.properties, "$ai_generation_id", "$ai_span_id"))
        if node_id is None:
            node_id = event.id
        events_by_node_id[node_id] = event

    child_ids: dict[str, list[str]] = {}
    for node_id, event in events_by_node_id.items():
        parent_id = _normalize_hierarchy_id(_first_set_property(event.properties, "$ai_parent_id", "$ai_trace_id"))
        if parent_id is not None:
            child_ids.setdefault(parent_id, []).append(node_id)

    def sort_key(node_id: str) -> _TraceEventSortKey:
        event = events_by_node_id[node_id]
        # Siblings that began together are ordered longest first, matching the timeline.
        return _TraceEventSortKey(
            operation_start_ms=_operation_start_ms(event), negative_latency_ms=-_latency_ms(event)
        )

    emitted_node_ids: set[str] = set()

    def build(node_id: str, depth: int) -> dict[str, Any] | None:
        event = events_by_node_id.get(node_id)
        if event is None or node_id in emitted_node_ids or depth > MAX_TREE_DEPTH:
            return None
        emitted_node_ids.add(node_id)
        children = sorted(child_ids.get(node_id, []), key=sort_key)
        return {
            "event": _to_formatter_event(event),
            "children": [node for node in (build(child_id, depth + 1) for child_id in children) if node is not None],
        }

    # An event whose parent never made it into the trace still has to be rendered, so it becomes a root.
    orphan_ids = [
        node_id
        for node_id, event in events_by_node_id.items()
        if (
            parent_id := _normalize_hierarchy_id(_first_set_property(event.properties, "$ai_parent_id", "$ai_trace_id"))
        )
        is not None
        and parent_id != llm_trace.id
        and parent_id not in events_by_node_id
    ]
    root_ids = sorted([*child_ids.get(llm_trace.id, []), *orphan_ids], key=sort_key)
    hierarchy = [node for node in (build(root_id, 0) for root_id in root_ids) if node is not None]

    # Start unvisited components at a new root so cycles and depth-limited branches still render once.
    remaining_root_ids = sorted(
        (node_id for node_id in events_by_node_id if node_id not in emitted_node_ids), key=sort_key
    )
    hierarchy.extend(node for node in (build(root_id, 0) for root_id in remaining_root_ids) if node is not None)
    return hierarchy


def llm_trace_to_formatter_format(
    llm_trace: LLMTrace, *, nest_children: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Convert an LLMTrace object to the format expected by format_trace_text_repr.

    Args:
        llm_trace: The LLMTrace object from TraceQueryRunner
        nest_children: Reconstruct the parent/child hierarchy instead of returning every event as a
            root. Callers that render a trace for a reader want this; the flat shape is kept as the
            default so existing prompts and evaluations see the events they saw before.

    Returns:
        A tuple of (trace_dict, hierarchy) suitable for format_trace_text_repr
    """
    trace_dict = {
        "id": llm_trace.id,
        "properties": {
            "$ai_trace_id": llm_trace.id,
            "$ai_span_name": llm_trace.traceName,
            "$ai_session_id": llm_trace.aiSessionId,
            "$ai_input_state": llm_trace.inputState,
            "$ai_output_state": llm_trace.outputState,
        },
    }

    if nest_children:
        return trace_dict, _nest_events(llm_trace)

    hierarchy = [{"event": _to_formatter_event(event), "children": []} for event in llm_trace.events]

    return trace_dict, hierarchy


def _format_latency(latency: Any) -> str:
    """Format latency to 2 decimal places. Coerces string-valued latencies before formatting."""
    try:
        return f"{float(latency):.2f}s"
    except (TypeError, ValueError):
        return str(latency)


def _format_cost(cost: Any) -> str:
    """Format cost in USD. Coerces string-valued costs before formatting."""
    try:
        return f"${float(cost):.4f}"
    except (TypeError, ValueError):
        return str(cost)


def _get_event_summary(event: dict[str, Any]) -> str:
    """
    Get a brief summary of an event for tree display.

    Returns a one-line summary like:
    - "my-generation (0.45s, $0.0023, gpt-4)"
    - "my-span (1.2s)"
    - "ERROR: my-generation (0.45s, gpt-4)"
    """
    props = event.get("properties", {})
    event_type = event.get("event", "unknown")

    if event_type == "$ai_generation":
        span_name = props.get("$ai_span_name") or props.get("$ai_model") or "generation"
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_time_to_first_token") is not None:
            parts.append(f"TTFT: {_format_latency(props['$ai_time_to_first_token'])}")

        if props.get("$ai_total_cost_usd") is not None:
            parts.append(_format_cost(props["$ai_total_cost_usd"]))

        if props.get("$ai_model"):
            parts.append(props["$ai_model"])

        if props.get("$ai_is_error") or props.get("$ai_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    if event_type == "$ai_span":
        span_name = props.get("$ai_span_name", "span")
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_is_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    if event_type == "$ai_embedding":
        span_name = props.get("$ai_span_name") or props.get("$ai_model") or "embedding"
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_total_cost_usd") is not None:
            parts.append(_format_cost(props["$ai_total_cost_usd"]))

        if props.get("$ai_model"):
            parts.append(props["$ai_model"])

        if props.get("$ai_is_error") or props.get("$ai_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    if event_type == "$ai_evaluation":
        eval_name = props.get("$ai_evaluation_name", "evaluation")
        result = props.get("$ai_evaluation_result")
        applicable = props.get("$ai_evaluation_applicable")
        runtime = props.get("$ai_evaluation_runtime")

        parts = []
        if runtime:
            parts.append(runtime)
        if applicable is False or applicable == "false":
            parts.append("N/A")
        elif result is True or result == "true":
            parts.append("PASS")
        elif result is False or result == "false":
            parts.append("FAIL")

        summary = eval_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    return event_type


def _format_state(state: Any, label: str, options: FormatterOptions | None = None) -> list[str]:
    """Format a state object for display."""
    if not state:
        return []

    try:
        # Check if state looks like messages (list of dicts with role/content)
        if isinstance(state, list) and len(state) > 0 and isinstance(state[0], dict):
            first_item = state[0]
            if "role" in first_item or "content" in first_item:
                # Format as messages using appropriate formatter (they add their own headers)
                if "INPUT" in label:
                    return format_input_messages(state, options)
                else:
                    # For output, pass state as choices (second param)
                    return format_output_messages(None, state, options)

        # For non-message state, add the label header
        lines = ["", f"{label}:", ""]

        if isinstance(state, str):
            content_lines, _ = truncate_content(state, options)
            lines.extend(content_lines)
            return lines

        if isinstance(state, dict) or isinstance(state, list):
            json_str = json.dumps(state, indent=2)
            content_lines, _ = truncate_content(json_str, options)
            lines.extend(content_lines)
            return lines

        lines.append(str(state))
        return lines
    except Exception:
        return ["", f"{label}:", "", str(state)]


def _get_node_prefix(event_type: str) -> str:
    """Get the display prefix for an event type."""
    if event_type == "$ai_generation":
        return "[GEN]"
    elif event_type == "$ai_span":
        return "[SPAN]"
    elif event_type == "$ai_embedding":
        return "[EMBED]"
    elif event_type == "$ai_evaluation":
        return "[EVAL]"
    else:
        return "[EVENT]"


def _is_expandable_event(event_type: str) -> bool:
    """Check if event type supports expandable content."""
    return event_type in ("$ai_generation", "$ai_span", "$ai_embedding", "$ai_evaluation")


def _render_collapsed_node(prefix: str, current_prefix: str, node_prefix: str, summary: str) -> str:
    """Render a collapsed node showing only summary."""
    return f"{prefix}{current_prefix}{node_prefix} {summary}"


def _render_expandable_node_with_markers(
    prefix: str,
    current_prefix: str,
    node_prefix: str,
    summary: str,
    event_id: str,
    content: str,
) -> str:
    """Render expandable node with markers for frontend."""
    encoded_content = base64.b64encode(content.encode()).decode()
    display_text = f"{node_prefix} {summary}"
    expandable_marker = f"<<<GEN_EXPANDABLE|{event_id}|{display_text}|{encoded_content}>>>"
    return f"{prefix}{current_prefix}{expandable_marker}"


def _render_expandable_node_plain(
    prefix: str,
    current_prefix: str,
    child_prefix: str,
    node_prefix: str,
    summary: str,
    content: str,
) -> list[str]:
    """Render expandable node as plain text with full content inline."""
    lines = [f"{prefix}{current_prefix}[+] {node_prefix} {summary}"]
    for line in content.split("\n"):
        lines.append(f"{prefix}{child_prefix}    {line}")
    return lines


def _render_event_node(
    event: dict[str, Any],
    summary: str,
    prefix: str,
    current_prefix: str,
    child_prefix: str,
    options: FormatterOptions,
    collapsed: bool,
    include_markers: bool,
) -> list[str]:
    """Render a single event node based on its type and options."""
    event_type = event.get("event", "unknown")
    event_id = event.get("id", "unknown")
    node_prefix = _get_node_prefix(event_type)

    if collapsed:
        return [_render_collapsed_node(prefix, current_prefix, node_prefix, summary)]

    if not _is_expandable_event(event_type):
        if include_markers:
            clickable_prefix = f"<<<EVENT_LINK|{event_id}|{node_prefix}>>>"
            return [f"{prefix}{current_prefix}{clickable_prefix} {summary}"]
        return [f"{prefix}{current_prefix}{node_prefix} {summary}"]

    # Expandable event - disable line numbers for embedded content
    event_options: FormatterOptions = (
        {**options, "include_line_numbers": False} if options else {"include_line_numbers": False}
    )
    event_content = format_event_text_repr(event, event_options)

    if include_markers:
        return [
            _render_expandable_node_with_markers(prefix, current_prefix, node_prefix, summary, event_id, event_content)
        ]
    return _render_expandable_node_plain(prefix, current_prefix, child_prefix, node_prefix, summary, event_content)


def _render_tree(
    nodes: list[dict[str, Any]],
    options: FormatterOptions | None = None,
    prefix: str = "",
    is_last: bool = True,
    depth: int = 0,
) -> list[str]:
    """Render tree structure with ASCII art.

    Creates expandable nodes using:
    - <<<GEN_EXPANDABLE|eventId|displayText|encodedContent>>> for include_markers=True
    - Plain text [+] indicators for include_markers=False
    """
    lines: list[str] = []

    if depth > MAX_TREE_DEPTH:
        lines.append(f"{prefix}  [... max depth reached]")
        return lines

    options = options or {}  # ty: ignore[invalid-assignment]
    include_markers = options.get("include_markers", True)
    collapsed = options.get("collapsed", False)

    for i, node in enumerate(nodes):
        is_last_node = i == len(nodes) - 1
        current_prefix = "└─ " if is_last_node else "├─ "
        child_prefix = "   " if is_last_node else "│  "

        event = node.get("event", node)
        children = node.get("children", [])

        summary = _get_event_summary(event)

        node_lines = _render_event_node(
            event, summary, prefix, current_prefix, child_prefix, options, collapsed, include_markers
        )
        lines.extend(node_lines)

        if children:
            child_lines = _render_tree(
                children, options=options, prefix=prefix + child_prefix, is_last=is_last_node, depth=depth + 1
            )
            lines.extend(child_lines)

    return lines


def format_trace_text_repr(
    trace: dict[str, Any], hierarchy: list[dict[str, Any]], options: FormatterOptions | None = None
) -> tuple[str, bool]:
    """
    Format a complete trace with hierarchical event structure.

    Creates an ASCII tree view with clickable expandable nodes for generations/spans.

    Options:
        - collapsed: If True, show only tree structure without expandable content
        - include_markers: If True, use <<<MARKERS>>> for frontend, else plain text
        - truncated: Whether to truncate long content within events
        - truncate_buffer: Chars to show at start/end when truncating
        - include_line_numbers: If True, prefix each line with line number (L1:, L2:, etc.)

    Args:
        trace: The trace metadata with properties
        hierarchy: List of event nodes with children in tree structure
        options: Formatting options

    Returns:
        Tuple of (formatted_text, was_sampled) - the text representation and whether uniform sampling was applied
    """
    lines: list[str] = []
    props = trace.get("properties", {})

    # Trace header - support both camelCase (API) and snake_case (properties)
    trace_name = props.get("$ai_span_name") or trace.get("traceName") or trace.get("trace_name") or "TRACE"
    lines.append(trace_name.upper())
    lines.append("=" * 80)

    # Error information (if at trace level)
    if props.get("$ai_error"):
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("TRACE ERROR:")
        lines.append("")
        error = props["$ai_error"]
        if isinstance(error, str):
            lines.append(error)
        else:
            lines.append(json.dumps(error, indent=2))

    # Only show trace-level input/output if there are NO events in hierarchy
    # When events exist, the hierarchy tells the full story
    if not hierarchy:
        # Trace-level input state - check both locations
        input_state = props.get("$ai_input_state") or trace.get("inputState") or trace.get("input_state")
        input_lines = _format_state(input_state, "TRACE INPUT", options)
        if input_lines:
            lines.append("")
            lines.append(SEPARATOR)
            lines.extend(input_lines)

        # Trace-level output state - check both locations
        output_state = props.get("$ai_output_state") or trace.get("outputState") or trace.get("output_state")
        output_lines = _format_state(output_state, "TRACE OUTPUT", options)
        if output_lines:
            lines.append("")
            lines.append(SEPARATOR)
            lines.extend(output_lines)
    else:
        # Tree structure exists - show it instead of trace input/output
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("TRACE HIERARCHY:")
        lines.append("")
        lines.extend(_render_tree(hierarchy, options=options))

    formatted_text = "\n".join(lines)

    # Add line numbers if requested
    if options and options.get("include_line_numbers", False):
        formatted_text = add_line_numbers(formatted_text)

    # Apply max_length constraint by uniformly sampling lines if needed
    # Defaults to 2M chars to fit within LLM context windows
    max_length = options.get("max_length", DEFAULT_MAX_LENGTH) if options else DEFAULT_MAX_LENGTH
    was_sampled = False
    if max_length and len(formatted_text) > max_length:
        formatted_text, was_sampled = reduce_by_uniform_sampling(formatted_text, max_length)

    return formatted_text, was_sampled
