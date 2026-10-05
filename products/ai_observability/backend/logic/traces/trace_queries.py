import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models import Team, User

from .person import trace_distinct_id

TRACE_EVENT_NAMES = ("$ai_trace", "$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback")
# The largest result HogQL returns; without an explicit limit it returns 100 rows.
MAX_TRACE_EVENTS = 50_000
FALLBACK_BEFORE_HINT = timedelta(minutes=10)
FALLBACK_AFTER_HINT = timedelta(days=7)
# The legacy trace view used this date as its default range start when a link carried no timestamp.
UNHINTED_FALLBACK_START = datetime(2025, 1, 10, tzinfo=UTC)
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
class LoadedTrace:
    rows: tuple[TraceEventRow, ...]
    person: PersonRow | None


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


def _trace_rows_query() -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_select(),
        select_from=_ai_events(),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["event"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=name) for name in TRACE_EVENT_NAMES]),
                ),
                ast.Placeholder(expr=ast.Field(chain=["filter_conditions"])),
            ]
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=MAX_TRACE_EVENTS),
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
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["trace_id"]), right=ast.Constant(value=trace_id)
    )


@frozen
class FallbackWindow:
    start: datetime
    end: datetime


def fallback_window(timestamp_hint: datetime) -> FallbackWindow:
    """Raises OverflowError when the window around the hint leaves the datetime range."""
    return FallbackWindow(start=timestamp_hint - FALLBACK_BEFORE_HINT, end=timestamp_hint + FALLBACK_AFTER_HINT)


def _fallback_filter(trace_id: str, window: FallbackWindow | None) -> ast.Expr:
    if window is None:
        # The shared events table is not sorted by trace id, so a read without a window must not scan it.
        return ast.Constant(value=False)
    return ast.And(
        exprs=[
            _trace_filter(trace_id),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=window.start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=window.end),
            ),
        ]
    )


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
        fallback_placeholders={"filter_conditions": _fallback_filter(trace_id, window)},
    )
    return list(response.results or [])


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return value is True or value == 1


def _number(value: Any) -> float | None:
    # The events fallback reads untyped properties, so a count or cost can arrive as any string.
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    number = _number(value)
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
        session_id=_text(raw["session_id"]),
        parent_id=_text(raw["parent_id"]),
        span_id=_text(raw["span_id"]),
        generation_id=_text(raw["generation_id"]),
        span_name=_text(raw["span_name"]),
        trace_name=_text(raw["trace_name"]),
        model=_text(raw["model"]),
        provider=_text(raw["provider"]),
        **tokens,
        total_cost_usd=_number(raw["total_cost_usd"]),
        latency=_number(raw["latency"]),
        is_error=_flag(raw["is_error"]),
        error_is_truthy=is_truthy_json(raw["error_raw"]),
        ingestion_source=_text(raw["ingestion_source"]),
    )


def _read_person(team: Team, user: User | None, distinct_id: str) -> PersonRow:
    name = "ai_trace_person"
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(query=_person_query(distinct_id), team=team, user=user, query_type=name)
    email, person_name = response.results[0] if response.results else (None, None)
    return PersonRow(distinct_id=distinct_id, email=_text(email), name=_text(person_name))


def _read_rows(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> list[Sequence[Any]]:
    name = "ai_trace_rows"
    if timestamp_hint is not None:
        return _read(name, _trace_rows_query(), team, user, trace_id, fallback_window(timestamp_hint))
    results = _read(name, _trace_rows_query(), team, user, trace_id, None)
    if results:
        return results
    logger.warning("ai_trace_unhinted_events_fallback", team_id=team.pk, trace_id_length=len(trace_id))
    window = FallbackWindow(
        start=UNHINTED_FALLBACK_START - FALLBACK_BEFORE_HINT, end=datetime.now(UTC) + FALLBACK_AFTER_HINT
    )
    return _read(name, _trace_rows_query(), team, user, trace_id, window)


def load_trace(team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None) -> LoadedTrace:
    rows = tuple(_trace_event_row(values) for values in _read_rows(team, user, trace_id, timestamp_hint))
    distinct_id = trace_distinct_id(rows)
    person = _read_person(team, user, distinct_id) if distinct_id else None
    return LoadedTrace(rows=rows, person=person)
