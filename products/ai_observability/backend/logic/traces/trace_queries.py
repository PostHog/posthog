import json
import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from functools import reduce
from typing import Any, Self
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.models import Team, User

from .events_fallback import FallbackWindow, events_filter, fallback_window, unhinted_window
from .person import trace_distinct_id

NODE_EVENT_NAMES = ("$ai_span", "$ai_generation", "$ai_embedding")
TRACE_EVENT_NAMES = ("$ai_trace", *NODE_EVENT_NAMES)
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
    git_branch: str | None
    git_repo: str | None


@frozen
class GitStampRow:
    uuid: str
    timestamp: datetime
    git_branch: str | None
    git_repo: str | None


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
    "git_branch": ast.Field(chain=["properties", "$ai_git_branch"]),
    "git_repo": ast.Field(chain=["properties", "$ai_git_repo"]),
}


def _select(selected: dict[str, ast.Expr] = _SELECTED) -> list[ast.Expr]:
    return [
        expr if isinstance(expr, ast.Field) and expr.chain == [alias] else ast.Alias(alias=alias, expr=expr)
        for alias, expr in selected.items()
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


def _trace_rows_query(columns: Sequence[str] = tuple(_SELECTED)) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_select({column: _SELECTED[column] for column in columns}),
        select_from=_ai_events(),
        where=ast.And(exprs=[_event_in(TRACE_EVENT_NAMES), _filter_conditions()]),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])]),
        limit=ast.Constant(value=MAX_TRACE_EVENTS),
    )


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
    *,
    event_names: Sequence[str] = TRACE_EVENT_NAMES,
    settings: HogQLGlobalSettings | None = None,
    workload: Workload = Workload.DEFAULT,
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
                trace_filter=_trace_filter(trace_id), event_filter=_event_in(event_names), window=window
            )
        },
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
        git_branch=read_text(raw["git_branch"]),
        git_repo=read_text(raw["git_repo"]),
    )


def _read_person(team: Team, user: User | None, distinct_id: str, workload: Workload) -> PersonRow:
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
            workload=workload,
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


def load_trace(
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    workload: Workload = Workload.DEFAULT,
) -> LoadedTrace:
    rows = tuple(
        _trace_event_row(values)
        for values in _read_trace(
            "ai_trace_rows",
            _trace_rows_query,
            team,
            user,
            trace_id,
            timestamp_hint,
            widen_unhinted=True,
            workload=workload,
        )
    )
    distinct_id = trace_distinct_id(rows)
    person = _read_person(team, user, distinct_id, workload) if distinct_id else None
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


def load_trace_root(
    team: Team,
    user: User | None,
    trace_id: str,
    timestamp_hint: datetime | None,
    *,
    workload: Workload = Workload.DEFAULT,
) -> TraceRootLookup:
    def read(name: str, build_query: Callable[[], ast.SelectQuery]) -> list[Sequence[Any]]:
        return _read_trace(
            name, build_query, team, user, trace_id, timestamp_hint, widen_unhinted=False, workload=workload
        )

    results = read("ai_trace_root", lambda: _node_query(_equals("event", "$ai_trace")))
    if results:
        return TraceRootLookup(trace_event=_trace_node_row(results[0]), trace_found=True)
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
        select_from=_ai_events(),
        where=ast.And(exprs=[selection, _filter_conditions()]),
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


def _column_in(column: str, values: Sequence[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[column]),
        right=ast.Tuple(exprs=[ast.Constant(value=value) for value in values]),
    )


def _steps_named(node_ids: Sequence[str]) -> ast.Expr:
    uuids = [uuid for node_id in node_ids if (uuid := canonical_uuid(node_id))]
    return ast.Or(
        exprs=[
            _column_in("span_id", node_ids),
            _column_in("generation_id", node_ids),
            *([_column_in("uuid", uuids)] if uuids else []),
        ]
    )


def load_trace_feedback_rows(
    team: Team, user: User | None, trace_id: str, timestamp_hint: datetime | None
) -> tuple[FeedbackEventRow, ...]:
    """The trace's feedback and metric events, then the steps their parent ids name, so each entry finds its target.

    Most traces have no feedback, so the steps are read only when an entry names one."""

    def read(name: str, selection: ast.Expr, event_names: Sequence[str]) -> list[FeedbackEventRow]:
        results = _read_trace(
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

    feedback = read("ai_trace_feedback_rows", _event_in(FEEDBACK_EVENT_NAMES), FEEDBACK_EVENT_NAMES)
    parent_ids = sorted({row.parent_id for row in feedback if row.parent_id and row.parent_id != trace_id})
    if not parent_ids:
        return tuple(feedback)
    steps = read(
        "ai_trace_feedback_targets",
        ast.And(exprs=[_event_in(NODE_EVENT_NAMES), _steps_named(parent_ids)]),
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
    query = _trace_rows_query()
    return replace(query, select=[*query.select, ast.Alias(alias="match_count", expr=match_count)])


def load_trace_search(
    team: Team, user: User | None, trace_id: str, query: str, timestamp_hint: datetime | None
) -> LoadedTraceSearch:
    needles = SearchNeedles.of(query)
    results = _read_trace(
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
        for uuid, timestamp, branch, repo in _read_trace(
            "ai_trace_git", _git_stamps_query, team, user, trace_id, timestamp_hint, widen_unhinted=False
        )
    )
