import json
import math
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.models import Team, User

from .events_fallback import FallbackWindow, events_filter, fallback_window, unhinted_window
from .person import trace_distinct_id

TRACE_EVENT_NAMES = ("$ai_trace", "$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback")
NODE_EVENT_NAMES = ("$ai_span", "$ai_generation", "$ai_embedding")
_HEAVY_COLUMNS = ("input", "output", "output_choices", "input_state", "output_state", "tools")
_NODE_COLUMNS = ("uuid", "event", "timestamp", "properties", *_HEAVY_COLUMNS)
# The largest result HogQL returns; without an explicit limit it returns 100 rows.
MAX_TRACE_EVENTS = 50_000
TOKEN_PROPERTIES = {
    "input_tokens": "$ai_input_tokens",
    "output_tokens": "$ai_output_tokens",
    "cache_read_input_tokens": "$ai_cache_read_input_tokens",
    "cache_creation_input_tokens": "$ai_cache_creation_input_tokens",
}

logger = structlog.get_logger(__name__)


@frozen
class TraceEventRow:
    uuid: str
    event: str
    timestamp: datetime
    distinct_id: str
    session_id: str | None
    parent_id: str | None
    span_id: str | None
    generation_id: str | None
    span_name: str | None
    trace_name: str | None
    model: str | None
    provider: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None
    total_cost_usd: float | None
    latency: float | None
    is_error: bool
    error_is_truthy: bool
    ingestion_source: str | None


@frozen
class PersonRow:
    distinct_id: str
    email: str | None
    name: str | None


@frozen
class TraceNodeRow:
    uuid: str
    event: str
    timestamp: datetime
    properties: dict[str, Any]


@frozen
class LoadedTrace:
    rows: tuple[TraceEventRow, ...]
    person: PersonRow | None


@frozen
class TraceRootLookup:
    trace_event: TraceNodeRow | None
    trace_found: bool


def _raw_property(name: str) -> ast.Call:
    return ast.Call(name="JSONExtractRaw", args=[ast.Field(chain=["properties"]), ast.Constant(value=name)])


def _raw_token_property(column: str) -> ast.Call:
    # The native token columns read NULL for the {"total": N} objects older SDKs sent, so the raw value is read
    # only for those rows.
    return ast.Call(
        name="if",
        args=[
            ast.Call(name="isNull", args=[ast.Field(chain=[column])]),
            _raw_property(TOKEN_PROPERTIES[column]),
            ast.Constant(value=None),
        ],
    )


_NATIVE_COLUMNS = (
    "uuid",
    "event",
    "timestamp",
    "distinct_id",
    "session_id",
    "parent_id",
    "span_id",
    "generation_id",
    "span_name",
    "trace_name",
    "model",
    "provider",
    *TOKEN_PROPERTIES,
    "total_cost_usd",
    "latency",
    "is_error",
)
_SELECTED: dict[str, ast.Expr] = {
    **{column: ast.Field(chain=[column]) for column in _NATIVE_COLUMNS},
    **{f"{column}_raw": _raw_token_property(column) for column in TOKEN_PROPERTIES},
    # The native error column extracts $ai_error as a string, which loses the JSON type that decides truthiness.
    "error_raw": _raw_property("$ai_error"),
    "ingestion_source": ast.Field(chain=["properties", "$ai_ingestion_source"]),
}


def _select() -> list[ast.Expr]:
    return [
        expr if isinstance(expr, ast.Field) and expr.chain == [alias] else ast.Alias(alias=alias, expr=expr)
        for alias, expr in _SELECTED.items()
    ]


def _ai_events() -> ast.JoinExpr:
    return ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events")


def _event_in(names: Sequence[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in names]),
    )


def _equals(column: str, value: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Field(chain=[column]), right=ast.Constant(value=value)
    )


def _filter_conditions() -> ast.Placeholder:
    return ast.Placeholder(expr=ast.Field(chain=["filter_conditions"]))


def _trace_rows_query() -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_select(),
        select_from=_ai_events(),
        where=ast.And(exprs=[_event_in(TRACE_EVENT_NAMES), _filter_conditions()]),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=MAX_TRACE_EVENTS),
    )


def _node_query(selection: ast.Expr) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in _NODE_COLUMNS],
        select_from=_ai_events(),
        where=ast.And(exprs=[selection, _filter_conditions()]),
        limit=ast.Constant(value=1),
    )


def _node_selection(node_id: str) -> ast.Expr:
    return ast.And(exprs=[_event_in(NODE_EVENT_NAMES), _equals("uuid", node_id)])


def _trace_exists_query() -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=["uuid"])],
        select_from=_ai_events(),
        where=ast.And(exprs=[_event_in(TRACE_EVENT_NAMES), _filter_conditions()]),
        limit=ast.Constant(value=1),
    )


def _person_query(distinct_id: str) -> ast.SelectQuery:
    def latest(column: str) -> ast.Call:
        return ast.Call(name="argMax", args=[ast.Field(chain=[column]), ast.Field(chain=["version"])])

    # The person_distinct_ids table deduplicates every distinct id of the team before a filter applies, so the raw
    # table is filtered first to keep the read to one distinct id.
    person_id = ast.SelectQuery(
        select=[latest("person_id")],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_ids"])),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["distinct_id"]), right=ast.Constant(value=distinct_id)
        ),
        group_by=[ast.Field(chain=["distinct_id"])],
        having=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=latest("is_deleted"), right=ast.Constant(value=0)
        ),
    )
    return ast.SelectQuery(
        select=[ast.Field(chain=["properties", "email"]), ast.Field(chain=["properties", "name"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.CompareOperation(op=ast.CompareOperationOp.In, left=ast.Field(chain=["id"]), right=person_id),
        limit=ast.Constant(value=1),
    )


def _trace_filter(trace_id: str) -> ast.Expr:
    return _equals("trace_id", trace_id)


def _read(
    name: str,
    query: ast.SelectQuery,
    team: Team,
    user: User | None,
    trace_id: str,
    window: FallbackWindow | None,
) -> list[Sequence[Any]]:
    tag_queries(name=name)
    response = query_ai_events(
        query=query,
        placeholders={"filter_conditions": _trace_filter(trace_id)},
        team=team,
        user=user,
        query_type=name,
        fall_back_to_events=True,
        fallback_placeholders={
            "filter_conditions": events_filter(
                trace_filter=_trace_filter(trace_id), event_filter=_event_in(TRACE_EVENT_NAMES), window=window
            )
        },
        posthog_tables_only=True,
    )
    return list(response.results or [])


def read_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def read_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return value is True or value == 1


def read_number(value: Any) -> float | None:
    # The events fallback reads untyped properties, so a count or cost can arrive as any string.
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    number = read_number(value)
    return None if number is None else int(number)


def _json(raw: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def is_truthy_json(raw: Any) -> bool:
    # A falsy $ai_error such as "", false or 0 does not mark an error, the same as in the legacy trace view.
    return bool(_json(raw))


def _token_count(native: Any, raw: Any) -> int | None:
    count = _count(native)
    if count is not None:
        return count
    value = _json(raw)
    if isinstance(value, dict):
        value = value.get("total")
    return _count(value)


def _trace_event_row(values: Sequence[Any]) -> TraceEventRow:
    raw = dict(zip(_SELECTED, values))
    tokens = {column: _token_count(raw[column], raw[f"{column}_raw"]) for column in TOKEN_PROPERTIES}
    return TraceEventRow(
        uuid=str(raw["uuid"]),
        event=str(raw["event"]),
        timestamp=raw["timestamp"],
        distinct_id=str(raw["distinct_id"]),
        session_id=read_text(raw["session_id"]),
        parent_id=read_text(raw["parent_id"]),
        span_id=read_text(raw["span_id"]),
        generation_id=read_text(raw["generation_id"]),
        span_name=read_text(raw["span_name"]),
        trace_name=read_text(raw["trace_name"]),
        model=read_text(raw["model"]),
        provider=read_text(raw["provider"]),
        **tokens,
        total_cost_usd=read_number(raw["total_cost_usd"]),
        latency=read_number(raw["latency"]),
        is_error=read_flag(raw["is_error"]),
        error_is_truthy=is_truthy_json(raw["error_raw"]),
        ingestion_source=read_text(raw["ingestion_source"]),
    )


def _read_person(team: Team, user: User | None, distinct_id: str) -> PersonRow:
    name = "ai_trace_person"
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=_person_query(distinct_id),
            team=team,
            user=user,
            query_type=name,
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
        )
    email, person_name = response.results[0] if response.results else (None, None)
    return PersonRow(distinct_id=distinct_id, email=read_text(email), name=read_text(person_name))


def _read_trace(
    name: str,
    build_query: Callable[[], ast.SelectQuery],
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    widen_unhinted: bool,
) -> list[Sequence[Any]]:
    if timestamp_hint is not None:
        return _read(name, build_query(), team, user, trace_id, fallback_window(timestamp_hint))
    results = _read(name, build_query(), team, user, trace_id, None)
    if results or not widen_unhinted:
        return results
    logger.warning("ai_trace_unhinted_events_fallback", team_id=team.pk, trace_id_length=len(trace_id), read=name)
    return _read(name, build_query(), team, user, trace_id, unhinted_window())


def load_trace(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> LoadedTrace:
    rows = tuple(
        _trace_event_row(values)
        for values in _read_trace(
            "ai_trace_rows", _trace_rows_query, team, user, trace_id, timestamp_hint, widen_unhinted=True
        )
    )
    distinct_id = trace_distinct_id(rows)
    person = _read_person(team, user, distinct_id) if distinct_id else None
    return LoadedTrace(rows=rows, person=person)


def canonical_uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _trace_node_row(values: Sequence[Any]) -> TraceNodeRow:
    raw = dict(zip(_NODE_COLUMNS, values))
    return TraceNodeRow(
        uuid=str(raw["uuid"]),
        event=str(raw["event"]),
        timestamp=raw["timestamp"],
        properties=merge_heavy_properties(raw["properties"], {column: raw[column] for column in _HEAVY_COLUMNS}),
    )


# Node ids come from links and can be stale or SDK ids, so node reads never widen to the unhinted events scan.
def load_trace_node(
    team: Team, user: User | None, trace_id: str, node_id: str, timestamp_hint: datetime | None
) -> TraceNodeRow | None:
    event_uuid = canonical_uuid(node_id)
    if event_uuid is None:
        return None
    results = _read_trace(
        "ai_trace_node",
        lambda: _node_query(_node_selection(event_uuid)),
        team,
        user,
        trace_id,
        timestamp_hint,
        widen_unhinted=False,
    )
    return _trace_node_row(results[0]) if results else None


def load_trace_root(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> TraceRootLookup:
    def read(name: str, build_query: Callable[[], ast.SelectQuery]) -> list[Sequence[Any]]:
        return _read_trace(name, build_query, team, user, trace_id, timestamp_hint, widen_unhinted=False)

    results = read("ai_trace_root", lambda: _node_query(_equals("event", "$ai_trace")))
    if results:
        return TraceRootLookup(trace_event=_trace_node_row(results[0]), trace_found=True)
    # Most traces have no $ai_trace event, so the existence check reads light columns instead of a step's payload.
    return TraceRootLookup(trace_event=None, trace_found=bool(read("ai_trace_exists", _trace_exists_query)))
