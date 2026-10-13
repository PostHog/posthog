from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    # Without `json_schema_serialization_defaults_required`, fields with defaults generate as optional in TypeScript.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        json_schema_serialization_defaults_required=True,
    )


TraceNodeKind = Literal["trace", "span", "generation", "embedding"]
TRACE_NODE_KINDS: tuple[TraceNodeKind, ...] = get_args(TraceNodeKind)


class TraceNodeStats(Contract):
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    latency_ms: float | None


class TraceNode(Contract):
    id: str
    kind: TraceNodeKind
    name: str
    model: str | None
    stats: TraceNodeStats
    has_error: bool
    children: list["TraceNode"]


class TraceTimelineRow(Contract):
    id: str
    kind: TraceNodeKind
    name: str
    depth: int
    start_ms: float
    duration_ms: float | None
    has_error: bool


class TracePerson(Contract):
    distinct_id: str
    label: str


class Trace(Contract):
    id: str
    name: str | None
    created_at: datetime
    session_id: str | None
    person: TracePerson | None
    totals: TraceNodeStats
    has_error: bool
    error_count: int
    tree: list[TraceNode]
    timeline: list[TraceTimelineRow]
    total_ms: float
    thread_node_ids: list[str]
