from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from posthog.models import Team

from products.ai_observability.backend.logic.traces.evaluation_result_queries import EvaluationResultRow
from products.ai_observability.backend.logic.traces.trace_queries import TraceEventRow

T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
EVALUATION_ID = "0192f2a4-5c1e-7000-8000-000000000e01"


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


def make_evaluation_result_row(**overrides: Any) -> EvaluationResultRow:
    fields: dict[str, Any] = {
        "uuid": "result-1",
        "timestamp": T0,
        "evaluation_id": EVALUATION_ID,
        "evaluation_name": "Answers the question",
        "target_event_id": None,
        "result": "true",
        "reasoning": "Direct answer.",
        "applicable": None,
        "evaluation_type": "llm_judge",
        "result_type": None,
        "sentiment_label": None,
        "skipped": None,
        "score": None,
        "categories": None,
        "backfill_id": None,
    }
    return EvaluationResultRow(**{**fields, **overrides})


def make_evaluation_result_event(
    *,
    uuid: str,
    team: Team,
    timestamp: datetime,
    trace_id: str = "trace-1",
    event: str = "$ai_evaluation",
    properties: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "event": event,
        "event_uuid": uuid,
        "distinct_id": "user-1",
        "team": team,
        "timestamp": timestamp,
        "properties": {"$ai_trace_id": trace_id, "$ai_evaluation_result": True, **(properties or {})},
    }
