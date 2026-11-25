import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from functools import reduce
from typing import Any, Self
from uuid import UUID

import structlog

from posthog.schema import HogQLQueryModifiers, MaterializationMode

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.hogql_queries.ai.ai_column_rewriter import (
    EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES,
    rewrite_expr_for_events_table,
    rewrite_query_for_events_table,
)
from posthog.hogql_queries.ai.ai_table_resolver import AI_EVENTS_QUERY_TOTAL, query_ai_events
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.models import Team, User
from posthog.models.event.new_events_schema import use_new_events_schema

from .error_text import error_text, is_truthy_json, parse_json
from .events_fallback import FallbackWindow, events_filter, fallback_window, unhinted_window
from .tool_calls import called_tool_names
from .trace_expression_queries import (
    AI_EVENTS_COLUMNS,
    NODE_EVENT_NAMES,
    TRACE_EVENT_NAMES,
    grouped,
    trace_cost,
    trace_latency,
    trace_person_id,
    trace_session_id,
)

_HEAVY_COLUMNS = ("input", "output", "output_choices", "input_state", "output_state", "tools")
NODE_COLUMNS = ("uuid", "event", "timestamp", "properties", *_HEAVY_COLUMNS)
# The largest result HogQL returns; without an explicit limit it returns 100 rows.
MAX_TRACE_EVENTS = MAX_SELECT_RETURNED_ROWS
TRACE_AVAILABILITY_QUERY_SECONDS = 2
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
    has_state: bool
    ingestion_source: str | None
    git_branch: str | None
    git_repo: str | None
    error_text: str | None
    tools_called: tuple[str, ...]
    is_support: bool
    trace_latency_s: float | None
    trace_cost_usd: float | None
    trace_distinct_id: str | None
    trace_session_id: str | None


@frozen
class GitStampRow:
    uuid: str
    timestamp: datetime
    git_branch: str | None
    git_repo: str | None


@frozen
class PersonRow:
    distinct_id: str
    display_name: str | None


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
    # None when the rows came from `posthog.ai_events`, which reads a trace by id with no time bound.
    read_start: datetime | None = None

    @property
    def truncated(self) -> bool:
        return len(self.rows) >= MAX_TRACE_EVENTS


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
    "has_state": ast.Placeholder(expr=ast.Field(chain=["has_state"])),
    "git_branch": ast.Field(chain=["properties", "$ai_git_branch"]),
    "git_repo": ast.Field(chain=["properties", "$ai_git_repo"]),
    "tools_called": ast.Field(chain=["properties", "$ai_tools_called"]),
    "is_support": ast.Field(chain=["properties", "ai_support_impersonated"]),
}


def _select(selected: dict[str, ast.Expr] = _SELECTED) -> list[ast.Expr]:
    return [
        expr if isinstance(expr, ast.Field) and expr.chain == [alias] else ast.Alias(alias=alias, expr=expr)
        for alias, expr in selected.items()
    ]


def ai_events() -> ast.JoinExpr:
    return ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events")


def event_in(names: Sequence[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in names]),
    )


def equals(column: str, value: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Field(chain=[column]), right=ast.Constant(value=value)
    )


def filter_conditions() -> ast.Placeholder:
    return ast.Placeholder(expr=ast.Field(chain=["filter_conditions"]))


def _trace_rows_query(columns: Sequence[str] = tuple(_SELECTED)) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_select({column: _SELECTED[column] for column in columns}),
        select_from=ai_events(),
        where=ast.And(exprs=[event_in(TRACE_EVENT_NAMES), filter_conditions()]),
        order_by=[
            ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC"),
            ast.OrderExpr(expr=ast.Field(chain=["uuid"]), order="ASC"),
        ],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=MAX_TRACE_EVENTS),
    )


def _column_name(expr: ast.Expr) -> str:
    if isinstance(expr, ast.Alias):
        return expr.alias
    assert isinstance(expr, ast.Field)
    return str(expr.chain[-1])


_TRACE_TOTALS = {
    "trace_latency_s": trace_latency,
    "trace_cost_usd": trace_cost,
    "trace_distinct_id": trace_person_id,
    "trace_session_id": trace_session_id,
}


# Only the columns the totals read, so the totals read stays narrow however wide the capped rows are.
_TRACE_TOTAL_INPUTS = ("event", "timestamp", "latency", "parent_id", "distinct_id", "session_id", "total_cost_usd")


def _trace_totals_query(rows: ast.SelectQuery) -> ast.SelectQuery:
    """Each trace's latency, cost, person and session over every deduplicated event `rows` filters to. A window over the
    wide rows would hold every row of a trace in memory before the cap, and this read holds one row per trace."""
    trace_id = ast.Field(chain=["trace_id"])
    narrow = replace(
        rows,
        select=[*_select({column: _SELECTED[column] for column in _TRACE_TOTAL_INPUTS}), trace_id],
        order_by=None,
        limit=None,
    )
    return ast.SelectQuery(
        select=[
            trace_id,
            *(ast.Alias(alias=alias, expr=build(AI_EVENTS_COLUMNS, grouped)) for alias, build in _TRACE_TOTALS.items()),
        ],
        select_from=ast.JoinExpr(table=narrow),
        group_by=[trace_id],
    )


def _join_trace_totals(
    capped: ast.SelectQuery, rows: ast.SelectQuery, *, before: Sequence[str], after: Sequence[str]
) -> ast.SelectQuery:
    """Selects the `before` columns of each capped row, its trace's totals over every row of `rows`, then the `after`
    columns, in the capped read's order. The capped read selects `trace_id`."""

    def side(alias: str, column: str) -> ast.Field:
        return ast.Field(chain=[alias, column])

    return ast.SelectQuery(
        select=[
            *(side("capped", column) for column in before),
            *(side("totals", alias) for alias in _TRACE_TOTALS),
            *(side("capped", column) for column in after),
        ],
        select_from=ast.JoinExpr(
            table=capped,
            alias="capped",
            next_join=ast.JoinExpr(
                join_type="JOIN",
                table=_trace_totals_query(rows),
                alias="totals",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=side("capped", "trace_id"),
                        right=side("totals", "trace_id"),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        order_by=capped.order_by,
        limit=capped.limit,
    )


def with_trace_totals(rows: ast.SelectQuery, *, limit: int | None, extra: Sequence[ast.Alias] = ()) -> ast.SelectQuery:
    """Gives each deduplicated row its trace's latency, cost, person and session, computed over every row of the trace
    before `limit` cuts the read. The `extra` columns come after the totals."""
    columns = [_column_name(expr) for expr in rows.select]
    trace_id = [] if "trace_id" in columns else [ast.Field(chain=["trace_id"])]
    capped = replace(
        rows,
        select=[*rows.select, *extra, *trace_id],
        limit=ast.Constant(value=limit) if limit is not None else None,
    )
    return _join_trace_totals(capped, rows, before=columns, after=[column.alias for column in extra])


def _git_stamps_query() -> ast.SelectQuery:
    # The stamps come from the same first events load_trace reads, so the chip and its pull request agree on a trace
    # longer than MAX_TRACE_EVENTS.
    columns = ("uuid", "timestamp", "git_branch", "git_repo")
    # HogQL makes `!=` true for NULL, so a missing branch is folded into the empty string first.
    branch = ast.Call(name="ifNull", args=[ast.Field(chain=["git_branch"]), ast.Constant(value="")])
    return ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in columns],
        select_from=ast.JoinExpr(table=_trace_rows_query(columns)),
        where=ast.Call(name="notEmpty", args=[branch]),
    )


def _node_query(selection: ast.Expr) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in NODE_COLUMNS],
        select_from=ai_events(),
        where=ast.And(exprs=[selection, filter_conditions()]),
        limit=ast.Constant(value=1),
    )


def _node_selection(node_id: str) -> ast.Expr:
    return ast.And(exprs=[event_in(NODE_EVENT_NAMES), equals("uuid", node_id)])


def _trace_exists_query() -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=["uuid"])],
        select_from=ai_events(),
        where=ast.And(exprs=[event_in(TRACE_EVENT_NAMES), filter_conditions()]),
        limit=ast.Constant(value=1),
    )


def _display_name(team: Team) -> ast.Expr:
    property_keys = team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    # An empty string becomes null, so the coalesce falls through to the next property as core's display name does.
    return ast.Call(
        name="coalesce",
        args=[
            ast.Call(
                name="nullIf",
                args=[
                    ast.Call(name="toString", args=[ast.Field(chain=["properties", key])]),
                    ast.Constant(value=""),
                ],
            )
            for key in property_keys
        ],
    )


def _mapped_person_ids(distinct_ids: Sequence[str]) -> ast.SelectQuery:
    def latest(column: str) -> ast.Call:
        return ast.Call(name="argMax", args=[ast.Field(chain=[column]), ast.Field(chain=["version"])])

    # The person_distinct_ids table deduplicates every distinct id of the team before a filter applies, so the raw
    # table is filtered first to keep the read to the requested distinct ids.
    return ast.SelectQuery(
        select=[ast.Field(chain=["distinct_id"]), ast.Alias(alias="mapped_person_id", expr=latest("person_id"))],
        select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_ids"])),
        where=column_in("distinct_id", distinct_ids),
        group_by=[ast.Field(chain=["distinct_id"])],
        having=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=latest("is_deleted"), right=ast.Constant(value=0)
        ),
    )


def _people_query(distinct_ids: Sequence[str], display_name: ast.Expr) -> ast.SelectQuery:
    # persons applies the id filter before it deduplicates person versions only when it is a query's own unaliased
    # FROM, so the persons read is a subquery of its own rather than the right side of the mapping join.
    persons = ast.SelectQuery(
        select=[ast.Field(chain=["id"]), ast.Alias(alias="display_name", expr=display_name)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["id"]),
            right=ast.SelectQuery(
                select=[ast.Field(chain=["mapped_person_id"])],
                select_from=ast.JoinExpr(table=_mapped_person_ids(distinct_ids)),
            ),
        ),
    )
    return ast.SelectQuery(
        select=[ast.Field(chain=["mapping", "distinct_id"]), ast.Field(chain=["people", "display_name"])],
        select_from=ast.JoinExpr(
            table=_mapped_person_ids(distinct_ids),
            alias="mapping",
            next_join=ast.JoinExpr(
                join_type="JOIN",
                table=persons,
                alias="people",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["people", "id"]),
                        right=ast.Field(chain=["mapping", "mapped_person_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        limit=ast.Constant(value=len(distinct_ids)),
    )


# SDKs send an empty state as `null`, `""` or `{}`, so a state of at most 4 bytes holds nothing to show.
_EMPTY_STATE_MAX_BYTES = 4


def _has_state(lengths: Iterable[ast.Expr]) -> ast.Expr:
    return ast.Or(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt, left=length, right=ast.Constant(value=_EMPTY_STATE_MAX_BYTES)
            )
            for length in lengths
        ]
    )


# ClickHouse reads the whole state column for any function of `input_state`, so ai_events checks the length
# subcolumns, which load no state content.
AI_EVENTS_HAS_STATE = _has_state((ast.Field(chain=["input_state_length"]), ast.Field(chain=["output_state_length"])))
# The events fallback reads the state from the properties JSON, where a missing key is an empty string.
EVENTS_HAS_STATE = _has_state(
    tuple(ast.Call(name="length", args=[ast.Field(chain=[column])]) for column in ("input_state", "output_state"))
)


def _trace_filter(trace_id: str) -> ast.Expr:
    return equals("trace_id", trace_id)


def ai_events_placeholders(trace_filter: ast.Expr) -> dict[str, ast.Expr]:
    return {"filter_conditions": trace_filter, "has_state": AI_EVENTS_HAS_STATE, "read_start": ast.Constant(value=None)}


def events_placeholders(
    trace_filter: ast.Expr, event_names: Sequence[str], window: FallbackWindow | None
) -> dict[str, ast.Expr]:
    return {
        "filter_conditions": events_filter(
            trace_filter=trace_filter, event_filter=event_in(event_names), window=window
        ),
        "has_state": EVENTS_HAS_STATE,
        "read_start": ast.Constant(value=window.start if window is not None else None),
    }


def _read(
    name: str,
    query: ast.SelectQuery,
    team: Team,
    user: User | None,
    trace_id: str,
    window: FallbackWindow | None,
    *,
    event_names: Sequence[str] = TRACE_EVENT_NAMES,
    settings: HogQLGlobalSettings | None = None,
    workload: Workload = Workload.DEFAULT,
) -> list[Sequence[Any]]:
    tag_queries(name=name)
    response = query_ai_events(
        query=query,
        placeholders=ai_events_placeholders(_trace_filter(trace_id)),
        team=team,
        user=user,
        query_type=name,
        fall_back_to_events=True,
        fallback_placeholders=events_placeholders(_trace_filter(trace_id), event_names, window),
        posthog_tables_only=True,
        settings=settings,
        workload=workload,
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


def _token_count(native: Any, raw: Any) -> int | None:
    count = _count(native)
    if count is not None:
        return count
    value = parse_json(raw)
    if isinstance(value, dict):
        value = value.get("total")
    return _count(value)


def _trace_event_row(values: Sequence[Any]) -> TraceEventRow:
    raw = dict(zip([*_SELECTED, *_TRACE_TOTALS], values))
    tokens = {column: _token_count(raw[column], raw[f"{column}_raw"]) for column in TOKEN_PROPERTIES}
    return TraceEventRow(
        uuid=str(raw["uuid"]),
        event=str(raw["event"]),
        timestamp=raw["timestamp"],
        distinct_id=str(raw["distinct_id"]),
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
        has_state=read_flag(raw["has_state"]),
        ingestion_source=read_text(raw["ingestion_source"]),
        git_branch=read_text(raw["git_branch"]),
        git_repo=read_text(raw["git_repo"]),
        error_text=error_text(raw["error_raw"]),
        tools_called=called_tool_names(raw["event"], raw["tools_called"]),
        is_support=read_flag(raw["is_support"]),
        trace_latency_s=read_number(raw["trace_latency_s"]),
        trace_cost_usd=read_number(raw["trace_cost_usd"]),
        trace_distinct_id=str(raw["trace_distinct_id"]) if raw["trace_distinct_id"] else None,
        trace_session_id=read_text(raw["trace_session_id"]),
    )


PEOPLE_QUERY_NAME = "ai_traces_people"
_TRACE_PERSON_QUERY_NAME = "ai_trace_person"


def load_people(
    team: Team,
    user: User | None,
    distinct_ids: Sequence[str],
    *,
    name: str = PEOPLE_QUERY_NAME,
    workload: Workload = Workload.ONLINE,
) -> dict[str, PersonRow]:
    requested = list(dict.fromkeys(distinct_ids))
    if not requested:
        return {}
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=_people_query(requested, _display_name(team)),
            team=team,
            user=user,
            query_type=name,
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
            workload=workload,
        )
    display_names = {str(distinct_id): read_text(display_name) for distinct_id, display_name in response.results}
    return {
        distinct_id: PersonRow(distinct_id=distinct_id, display_name=display_names.get(distinct_id))
        for distinct_id in requested
    }


def read_trace(
    name: str,
    build_query: Callable[[], ast.SelectQuery],
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    widen_unhinted: bool,
    event_names: Sequence[str] = TRACE_EVENT_NAMES,
    settings: HogQLGlobalSettings | None = None,
    workload: Workload = Workload.DEFAULT,
) -> list[Sequence[Any]]:
    def read(window: FallbackWindow | None) -> list[Sequence[Any]]:
        return _read(
            name,
            build_query(),
            team,
            user,
            trace_id,
            window,
            event_names=event_names,
            settings=settings,
            workload=workload,
        )

    if timestamp_hint is not None:
        return read(fallback_window(timestamp_hint))
    results = read(None)
    if results or not widen_unhinted:
        return results
    logger.warning("ai_trace_unhinted_events_fallback", team_id=team.pk, trace_id_length=len(trace_id), read=name)
    return read(unhinted_window())


def read_ai_events_table(
    name: str,
    query: ast.SelectQuery,
    team: Team,
    user: User | None,
    settings: HogQLGlobalSettings,
    placeholders: dict[str, ast.Expr] | None = None,
) -> list[Sequence[Any]]:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name, ai_query_source="dedicated_table")
        response = execute_hogql_query(
            query=query,
            placeholders=placeholders,
            team=team,
            user=user,
            query_type=name,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
            context=HogQLContext(
                team_id=team.pk, team=team, user=user, database=Database.create_for_posthog_tables(team)
            ),
            settings=settings,
            workload=Workload.ONLINE,
        )
    results = list(response.results or [])
    if results:
        AI_EVENTS_QUERY_TOTAL.labels(source="dedicated_table").inc()
    return results


def read_shared_events_table(
    name: str,
    query: ast.SelectQuery,
    team: Team,
    user: User | None,
    settings: HogQLGlobalSettings,
    placeholders: dict[str, ast.Expr] | None = None,
) -> list[Sequence[Any]]:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name, ai_query_source="shared_table_fallback")
        AI_EVENTS_QUERY_TOTAL.labels(source="shared_table_fallback").inc()
        response = execute_hogql_query(
            query=rewrite_query_for_events_table(query),
            placeholders={key: rewrite_expr_for_events_table(value) for key, value in (placeholders or {}).items()},
            team=team,
            user=user,
            query_type=name,
            context=HogQLContext(
                team_id=team.pk,
                team=team,
                user=user,
                database=Database.create_for_posthog_tables(team),
                use_new_events_schema=use_new_events_schema(team.pk),
                property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES,
            ),
            settings=settings,
            workload=Workload.ONLINE,
        )
    return list(response.results or [])


def _read_trace_availability(
    team: Team, user: User | None, trace_ids: Sequence[str], *, shared_events: bool = False
) -> list[str]:
    trace_filter = ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=ast.Field(chain=["trace_id"]), right=ast.Constant(value=list(trace_ids))
    )
    event_filter = event_in(TRACE_EVENT_NAMES)
    query = ast.SelectQuery(
        select=[ast.Field(chain=["trace_id"])],
        select_from=ai_events(),
        where=events_filter(trace_filter=trace_filter, event_filter=event_filter, window=unhinted_window())
        if shared_events
        else ast.And(exprs=[trace_filter, event_filter]),
        distinct=True,
        limit=ast.Constant(value=len(trace_ids)),
    )
    read = read_shared_events_table if shared_events else read_ai_events_table
    settings = HogQLGlobalSettings(
        max_execution_time=TRACE_AVAILABILITY_QUERY_SECONDS,
        timeout_before_checking_execution_speed=0,
        timeout_overflow_mode="break",
    )
    try:
        results = read("ai_trace_availability", query, team, user, settings)
    except ClickHouseQueryTimeOut:
        return []
    return [str(row[0]) for row in results]


def load_available_trace_ids(team: Team, user: User | None, trace_ids: Sequence[str]) -> list[str]:
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return []
    available = set(_read_trace_availability(team, user, requested))
    missing = [trace_id for trace_id in requested if trace_id not in available]
    if missing:
        available.update(_read_trace_availability(team, user, missing, shared_events=True))
    return [trace_id for trace_id in requested if trace_id in available]


# The placeholders give each table's read its own lower time bound, so the rows say which table answered.
_READ_START = ast.Alias(alias="read_start", expr=ast.Placeholder(expr=ast.Field(chain=["read_start"])))


def load_trace(
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    workload: Workload = Workload.DEFAULT,
) -> LoadedTrace:
    results = read_trace(
        "ai_trace_rows",
        lambda: with_trace_totals(_trace_rows_query(), limit=MAX_TRACE_EVENTS, extra=[_READ_START]),
        team,
        user,
        trace_id,
        timestamp_hint,
        widen_unhinted=True,
        workload=workload,
    )
    rows = tuple(_trace_event_row(values) for *values, _read_start in results)
    distinct_id = rows[0].trace_distinct_id if rows else None
    person = (
        load_people(team, user, [distinct_id], name=_TRACE_PERSON_QUERY_NAME, workload=workload)[distinct_id]
        if distinct_id
        else None
    )
    return LoadedTrace(rows=rows, person=person, read_start=results[0][-1] if results else None)


PAGE_ROWS_QUERY_NAME = "ai_traces_page_rows"
PAGE_ROW_CAP_PER_TRACE = 2000
# HogQL silently cuts a result at this many rows, so the page's caps are sized to fit inside it.
PAGE_ROW_BUDGET = MAX_SELECT_RETURNED_ROWS
_PAGE_ROWS_QUERY_SECONDS = 15


@frozen
class PageTraceRows:
    rows: tuple[TraceEventRow, ...]
    truncated: bool
    from_shared_table: bool


@frozen
class _PageRead:
    rows: list[Sequence[Any]]
    shared_table_trace_ids: frozenset[str]


def rows_per_trace_cap(trace_count: int) -> int:
    # Each trace reads one row past its cap to tell a truncated trace apart from one that fits exactly.
    return min(PAGE_ROW_CAP_PER_TRACE, PAGE_ROW_BUDGET // trace_count - 1)


def _page_rows_query(trace_count: int, cap: int) -> ast.SelectQuery:
    trace_rows = _trace_rows_query()
    # HogQL takes one LIMIT BY per query, so duplicates of an event are dropped before the per-trace cap.
    deduplicated = replace(
        trace_rows, select=[*trace_rows.select, ast.Field(chain=["trace_id"])], order_by=None, limit=None
    )
    capped = ast.SelectQuery(
        select=[*(ast.Field(chain=[column]) for column in _SELECTED), ast.Field(chain=["trace_id"])],
        select_from=ast.JoinExpr(table=deduplicated),
        order_by=[
            ast.OrderExpr(expr=equals("event", "$ai_trace"), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC"),
            ast.OrderExpr(expr=ast.Field(chain=["uuid"]), order="ASC"),
        ],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=cap + 1), exprs=[ast.Field(chain=["trace_id"])]),
        limit=ast.Constant(value=trace_count * (cap + 1)),
    )
    return _join_trace_totals(capped, trace_rows, before=list(_SELECTED), after=["trace_id"])


def _page_rows_settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_PAGE_ROWS_QUERY_SECONDS)


def _page_trace_rows(read: _PageRead, cap: int) -> dict[str, PageTraceRows]:
    by_trace: dict[str, list[TraceEventRow]] = {}
    for *values, trace_id in read.rows:
        by_trace.setdefault(str(trace_id), []).append(_trace_event_row(values))
    # The read orders each trace's rows trace event first, then by time and uuid, so the cut keeps the earliest rows
    # and keeps the same rows on every read.
    return {
        trace_id: PageTraceRows(
            rows=tuple(rows[:cap]),
            truncated=len(rows) > cap,
            from_shared_table=trace_id in read.shared_table_trace_ids,
        )
        for trace_id, rows in by_trace.items()
    }


def _read_page(
    name: str,
    build_query: Callable[[int], ast.SelectQuery],
    team: Team,
    user: User | None,
    trace_ids: Sequence[str],
    window: FallbackWindow,
) -> _PageRead:
    """Reads the traces from `posthog.ai_events`, then the ones it misses from the shared events table inside the
    window. `build_query` takes the number of traces read and selects the trace id last."""
    results = read_ai_events_table(
        name,
        build_query(len(trace_ids)),
        team,
        user,
        _page_rows_settings(),
        ai_events_placeholders(column_in("trace_id", trace_ids)),
    )
    found = {str(row[-1]) for row in results}
    missing = [trace_id for trace_id in trace_ids if trace_id not in found]
    if missing:
        results += read_shared_events_table(
            name,
            build_query(len(missing)),
            team,
            user,
            _page_rows_settings(),
            events_placeholders(column_in("trace_id", missing), TRACE_EVENT_NAMES, window),
        )
    return _PageRead(rows=results, shared_table_trace_ids=frozenset(missing))


def load_traces_rows(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow
) -> dict[str, PageTraceRows]:
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    cap = rows_per_trace_cap(len(requested))
    results = _read_page(
        PAGE_ROWS_QUERY_NAME,
        lambda trace_count: _page_rows_query(trace_count, cap),
        team,
        user,
        requested,
        window,
    )
    return _page_trace_rows(results, cap)


TRACE_USERS_QUERY_NAME = "ai_traces_users"


def _trace_users_query(trace_count: int) -> ast.SelectQuery:
    trace_id = ast.Field(chain=["trace_id"])
    return ast.SelectQuery(
        select=[ast.Alias(alias="person_distinct_id", expr=trace_person_id(AI_EVENTS_COLUMNS, grouped)), trace_id],
        select_from=ai_events(),
        where=ast.And(exprs=[event_in(TRACE_EVENT_NAMES), filter_conditions()]),
        group_by=[trace_id],
        limit=ast.Constant(value=trace_count),
    )


def load_trace_distinct_ids(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow
) -> dict[str, str]:
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    read = _read_page(TRACE_USERS_QUERY_NAME, _trace_users_query, team, user, requested, window)
    return {str(trace_id): str(distinct_id) for distinct_id, trace_id in read.rows if distinct_id}


def canonical_uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


def trace_node_row(values: Sequence[Any]) -> TraceNodeRow:
    raw = dict(zip(NODE_COLUMNS, values))
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
    results = read_trace(
        "ai_trace_node",
        lambda: _node_query(_node_selection(event_uuid)),
        team,
        user,
        trace_id,
        timestamp_hint,
        widen_unhinted=False,
    )
    return trace_node_row(results[0]) if results else None


def load_trace_root(
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    workload: Workload = Workload.DEFAULT,
) -> TraceRootLookup:
    def read(name: str, build_query: Callable[[], ast.SelectQuery]) -> list[Sequence[Any]]:
        return read_trace(
            name, build_query, team, user, trace_id, timestamp_hint, widen_unhinted=False, workload=workload
        )

    results = read("ai_trace_root", lambda: _node_query(equals("event", "$ai_trace")))
    if results:
        return TraceRootLookup(trace_event=trace_node_row(results[0]), trace_found=True)
    # Most traces have no $ai_trace event, so the existence check reads light columns instead of a step's payload.
    return TraceRootLookup(trace_event=None, trace_found=bool(read("ai_trace_exists", _trace_exists_query)))


METRIC_EVENT = "$ai_metric"
FEEDBACK_EVENT = "$ai_feedback"
FEEDBACK_EVENT_NAMES = (METRIC_EVENT, FEEDBACK_EVENT)


@frozen
class FeedbackEventRow:
    uuid: str
    event: str
    timestamp: datetime
    parent_id: str | None
    span_id: str | None
    generation_id: str | None
    metric_name: str | None
    metric_value_json: str
    feedback_text_json: str


_FEEDBACK_SELECTED: dict[str, ast.Expr] = {
    **{
        column: ast.Field(chain=[column])
        for column in ("uuid", "event", "timestamp", "parent_id", "span_id", "generation_id")
    },
    "metric_name": ast.Field(chain=["properties", "$ai_metric_name"]),
    # The raw JSON keeps the value's type, so a 0 or false score stays apart from a missing one.
    "metric_value_json": _raw_property("$ai_metric_value"),
    "feedback_text_json": _raw_property("$ai_feedback_text"),
}


def _feedback_rows_query(selection: ast.Expr) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_select(_FEEDBACK_SELECTED),
        select_from=ai_events(),
        where=ast.And(exprs=[selection, filter_conditions()]),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=MAX_TRACE_EVENTS),
    )


def _feedback_event_row(values: Sequence[Any]) -> FeedbackEventRow:
    raw = dict(zip(_FEEDBACK_SELECTED, values))
    return FeedbackEventRow(
        uuid=str(raw["uuid"]),
        event=str(raw["event"]),
        timestamp=raw["timestamp"],
        parent_id=read_text(raw["parent_id"]),
        span_id=read_text(raw["span_id"]),
        generation_id=read_text(raw["generation_id"]),
        metric_name=read_text(raw["metric_name"]),
        metric_value_json=raw["metric_value_json"] or "",
        feedback_text_json=raw["feedback_text_json"] or "",
    )


def column_in(column: str, values: Sequence[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[column]),
        right=ast.Tuple(exprs=[ast.Constant(value=value) for value in values]),
    )


def _steps_named(node_ids: Sequence[str]) -> ast.Expr:
    uuids = [uuid for node_id in node_ids if (uuid := canonical_uuid(node_id))]
    return ast.Or(
        exprs=[
            column_in("span_id", node_ids),
            column_in("generation_id", node_ids),
            *([column_in("uuid", uuids)] if uuids else []),
        ]
    )


def load_trace_feedback_rows(
    team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None
) -> tuple[FeedbackEventRow, ...]:
    """The trace's feedback and metric events, then the steps their parent ids name, so each entry finds its target.

    Most traces have no feedback, so the steps are read only when an entry names one."""

    def read(name: str, selection: ast.Expr, event_names: Sequence[str]) -> list[FeedbackEventRow]:
        results = read_trace(
            name,
            lambda: _feedback_rows_query(selection),
            team,
            user,
            trace_id,
            timestamp_hint,
            widen_unhinted=False,
            event_names=event_names,
        )
        return [_feedback_event_row(values) for values in results]

    feedback = read("ai_trace_feedback_rows", event_in(FEEDBACK_EVENT_NAMES), FEEDBACK_EVENT_NAMES)
    parent_ids = sorted({row.parent_id for row in feedback if row.parent_id and row.parent_id != trace_id})
    if not parent_ids:
        return tuple(feedback)
    steps = read(
        "ai_trace_feedback_targets",
        ast.And(exprs=[event_in(NODE_EVENT_NAMES), _steps_named(parent_ids)]),
        NODE_EVENT_NAMES,
    )
    return (*feedback, *steps)


_SEARCH_TIMEOUT_SECONDS = 10
_JSON_SEARCHED = (*(ast.Field(chain=[column]) for column in _HEAVY_COLUMNS), _raw_property("$ai_error"))
_TEXT_SEARCHED = tuple(ast.Field(chain=[column]) for column in ("span_name", "trace_name", "model", "provider"))
_ESCAPED_BACKSLASH = "\\\\"
_ESCAPED_BACKSLASH_MARK = "\x01"


def _json_escaped(value: str, *, ascii_only: bool = False) -> str:
    return json.dumps(value, ensure_ascii=ascii_only)[1:-1]


@frozen
class SearchNeedles:
    text: str
    # The heavy columns hold raw JSON, so quotes and backslashes in the query match only in their escaped form. A
    # string that holds JSON, such as tool arguments, keeps its own escapes and is escaped a second time around them.
    json: tuple[str, ...]

    @classmethod
    def of(cls, query: str) -> Self:
        escaped = _json_escaped(query)
        needles = [escaped]
        for nested in (_json_escaped(_json_escaped(query, ascii_only=True)), _json_escaped(escaped)):
            # Each occurrence of a nested needle that holds a kept needle is already counted once.
            if not any(kept.lower() in nested.lower() for kept in needles):
                needles.append(nested)
        return cls(text=query, json=tuple(needles))


@frozen
class LoadedTraceSearch:
    rows: tuple[TraceEventRow, ...]
    counts: dict[str, int]


def _search_settings() -> HogQLGlobalSettings:
    # Search reads every stored byte of the trace, so it fails fast instead of holding a request for the default minute.
    return HogQLGlobalSettings(max_execution_time=_SEARCH_TIMEOUT_SECONDS, timeout_overflow_mode="throw")


def _occurrences(haystack: ast.Expr, needle: str) -> ast.Expr:
    return ast.Call(
        name="ifNull",
        args=[
            ast.Call(name="countSubstringsCaseInsensitiveUTF8", args=[haystack, ast.Constant(value=needle)]),
            ast.Constant(value=0),
        ],
    )


def _json_occurrences(column: ast.Expr, needle: str) -> ast.Expr:
    if not needle.startswith("\\"):
        return _occurrences(column, needle)
    # A needle that starts with a backslash can match the second half of an escaped backslash, as `\"` matches the
    # end of `"C:\\"`. Raw JSON never holds a raw control byte, so each escaped backslash becomes one such byte first.
    marked = ast.Call(
        name="replaceAll",
        args=[column, ast.Constant(value=_ESCAPED_BACKSLASH), ast.Constant(value=_ESCAPED_BACKSLASH_MARK)],
    )
    return _occurrences(marked, needle.replace(_ESCAPED_BACKSLASH, _ESCAPED_BACKSLASH_MARK))


def _trace_search_query(needles: SearchNeedles) -> ast.SelectQuery:
    counts = [
        *(_json_occurrences(column, needle) for column in _JSON_SEARCHED for needle in needles.json),
        *(_occurrences(column, needles.text) for column in _TEXT_SEARCHED),
    ]
    match_count = reduce(lambda left, right: ast.Call(name="plus", args=[left, right]), counts)
    return with_trace_totals(
        _trace_rows_query(), limit=MAX_TRACE_EVENTS, extra=[ast.Alias(alias="match_count", expr=match_count)]
    )


def load_trace_search(
    team: Team, user: User | None, trace_id: str, query: str, timestamp_hint: datetime | None
) -> LoadedTraceSearch:
    needles = SearchNeedles.of(query)
    results = read_trace(
        "ai_trace_search",
        lambda: _trace_search_query(needles),
        team,
        user,
        trace_id,
        timestamp_hint,
        widen_unhinted=False,
        settings=_search_settings(),
    )
    rows: list[TraceEventRow] = []
    counts: dict[str, int] = {}
    for *values, match_count in results:
        row = _trace_event_row(values)
        rows.append(row)
        if match_count:
            counts[row.uuid] = int(match_count)
    return LoadedTraceSearch(rows=tuple(rows), counts=counts)


def load_trace_git_rows(
    team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None
) -> tuple[GitStampRow, ...]:
    return tuple(
        GitStampRow(uuid=str(uuid), timestamp=timestamp, git_branch=read_text(branch), git_repo=read_text(repo))
        for uuid, timestamp, branch, repo in read_trace(
            "ai_trace_git", _git_stamps_query, team, user, trace_id, timestamp_hint, widen_unhinted=False
        )
    )
