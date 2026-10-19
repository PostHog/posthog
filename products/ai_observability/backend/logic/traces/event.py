from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from ...facade.contracts import TraceNodeKind
from .trace_queries import TraceEventRow
from .usage import Usage

ANNOTATION_EVENTS = frozenset({"$ai_feedback", "$ai_metric"})


@frozen
class TraceEvent:
    row: TraceEventRow
    trace_id: str

    @property
    def id(self) -> str:
        return self.row.uuid

    @property
    def node_key(self) -> str:
        return self.row.generation_id or self.row.span_id or self.row.uuid

    @property
    def parent_key(self) -> str:
        return self.row.parent_id or self.trace_id

    @property
    def kind(self) -> TraceNodeKind:
        match self.row.event:
            case "$ai_generation":
                return "generation"
            case "$ai_embedding":
                return "embedding"
            case "$ai_trace":
                return "trace"
            case _:
                return "span"

    @property
    def is_trace_event(self) -> bool:
        return self.row.event == "$ai_trace"

    @property
    def is_annotation(self) -> bool:
        return self.row.event in ANNOTATION_EVENTS

    @property
    def has_error(self) -> bool:
        return self.row.is_error or self.row.error_is_truthy

    @property
    def usage(self) -> Usage:
        return Usage(
            cost_usd=self.row.total_cost_usd,
            latency_s=self.row.latency,
            input_tokens=self.row.input_tokens,
            output_tokens=self.row.output_tokens,
            cache_read_tokens=self.row.cache_read_input_tokens,
            cache_write_tokens=self.row.cache_creation_input_tokens,
        )

    @property
    def started_at(self) -> datetime:
        # PostHog SDKs capture an event when the operation ends; OTel-ingested spans keep the span start.
        if self.row.ingestion_source == "otel":
            return self.row.timestamp
        try:
            return self.row.timestamp - timedelta(milliseconds=self.usage.latency_ms or 0)
        except OverflowError:
            return self.row.timestamp

    @property
    def title(self) -> str:
        if self.kind in ("generation", "embedding"):
            if self.row.span_name:
                return self.row.span_name
            title = self.row.model or ("Generation" if self.kind == "generation" else "Embedding")
            return f"{title} ({self.row.provider})" if self.row.provider else title
        return self.row.span_name or "Span"

    @property
    def timeline_label(self) -> str:
        return self.row.span_name or self.row.model or self.row.event
