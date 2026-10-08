from datetime import UTC, datetime
from typing import Any

from products.ai_observability.backend.logic.traces.trace_queries import TraceEventRow

T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


def make_row(**overrides: Any) -> TraceEventRow:
    fields: dict[str, Any] = {
        "uuid": "event-1",
        "event": "$ai_span",
        "timestamp": T0,
        "distinct_id": "user-1",
        "session_id": None,
        "parent_id": "trace-1",
        "span_id": None,
        "generation_id": None,
        "span_name": None,
        "trace_name": None,
        "model": None,
        "provider": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_input_tokens": None,
        "cache_creation_input_tokens": None,
        "total_cost_usd": None,
        "latency": None,
        "is_error": False,
        "error_is_truthy": False,
        "ingestion_source": None,
    }
    return TraceEventRow(**{**fields, **overrides})
