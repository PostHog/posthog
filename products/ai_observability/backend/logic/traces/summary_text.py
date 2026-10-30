from collections.abc import Sequence
from typing import Any

from ...text_repr.formatters import FormatterOptions, TraceTextRepr, format_trace_text_repr_with_line_owners
from .trace import Trace
from .trace_queries import TraceNodeRow
from .tree import TreeNode

_TRACE_PROPERTIES = ("$ai_input_state", "$ai_output_state", "$ai_error")


def render_trace(
    trace: Trace, trace_event: TraceNodeRow | None, steps: Sequence[TraceNodeRow], budget: int
) -> TraceTextRepr:
    """The trace as the line-numbered text a summarization model reads, at most `budget` characters long.

    `trace_event` is the trace's own `$ai_trace` event, when it has one, and `steps` hold the contents of its
    nodes. A node without contents renders with its kind only."""
    properties_by_id = {row.uuid: row.properties for row in steps}

    def to_formatter_node(node: TreeNode) -> dict[str, Any]:
        return {
            "event": {
                "id": node.event.id,
                "event": node.event.row.event,
                "properties": properties_by_id.get(node.event.id, {}),
                "timestamp": node.event.row.timestamp.isoformat(),
            },
            "children": [to_formatter_node(child) for child in node.children],
        }

    trace_properties = trace_event.properties if trace_event is not None else {}
    formatter_trace = {
        "id": trace.id,
        "properties": {
            "$ai_trace_id": trace.id,
            "$ai_span_name": trace.name,
            "$ai_session_id": trace.session_id,
            **{key: trace_properties[key] for key in _TRACE_PROPERTIES if trace_properties.get(key) is not None},
        },
    }
    options: FormatterOptions = {
        "include_line_numbers": True,
        "truncated": False,
        "include_markers": False,
        "collapsed": False,
        "max_length": budget,
    }
    return format_trace_text_repr_with_line_owners(
        formatter_trace, [to_formatter_node(node) for node in trace.tree], options
    )
