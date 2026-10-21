from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
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
    default_node_id: str
    node_ids_by_alias: dict[str, str]


class TraceNodeIOKeys(Contract):
    input: str | None
    output: str | None
    tools: str | None


class TraceNodeMetadata(Contract):
    provider: str | None
    temperature: float | None
    session_id: str | None
    prompt_name: str | None
    prompt_version: float | None


class TraceNodeEvent(Contract):
    name: str
    uuid: str
    timestamp: datetime
    properties: dict[str, Any] = Field(
        description="The event's properties as ingested, including its input and output values."
    )
    io_keys: TraceNodeIOKeys = Field(
        description="Which keys of `properties` hold the node's input, output and tools, or null when it has none."
    )


class TraceNodeDetail(Contract):
    id: str
    kind: TraceNodeKind
    error: str | None
    metadata: TraceNodeMetadata
    event: TraceNodeEvent | None


class EvaluationPassFilters(Contract):
    """HogQL conditions over `$ai_evaluation` events, built from each evaluation's current output config."""

    graded: str  # The run counts toward a pass rate.
    passed: str  # The run passed. Implies `graded`.
