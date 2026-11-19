from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQueryTimeOut
from posthog.hogql_queries.ai.utils import parse_ai_property_value
from posthog.models import Team, User

from ..message_normalizer.values import Value
from .events_fallback import FallbackWindow, events_filter
from .previews import PreviewReads, TracePreviewSources, pick_preview_events, preview_sources, timed_out_sources
from .trace_queries import (
    AI_EVENTS_HAS_STATE,
    EVENTS_HAS_STATE,
    ai_events,
    column_in,
    event_in,
    read_ai_events_table,
    read_flag,
    read_shared_events_table,
)
from .turn import TURN_INPUT_TAIL

PREVIEW_PICKS_QUERY_NAME = "ai_traces_preview_picks"
PREVIEWS_QUERY_NAME = "ai_traces_previews"
PREVIEW_SOURCE_MAX_BYTES: Final = 65_536
_PREVIEW_QUERY_SECONDS = 15
_PICKED_EVENT_NAMES = ("$ai_trace", "$ai_generation")
_EVENT_COLUMNS = ("trace_id", "uuid", "event", "timestamp", "has_state")
_COLUMNS = {
    "$ai_input": "input",
    "$ai_output_choices": "output_choices",
    "$ai_output": "output",
    "$ai_input_state": "input_state",
    "$ai_output_state": "output_state",
}
_TAIL_PROPERTY = "$ai_input"


@frozen
class PreviewEventRow:
    trace_id: str
    uuid: str
    event: str
    timestamp: datetime
    has_state: bool


@frozen
class StoredValue:
    value: Value
    over_cap: bool
    # The input is read as its last items, with an item over the cap as null and flagged here by its position. A null
    # from the event itself is not flagged. None for a value not read as a tail.
    item_over_caps: tuple[bool, ...] | None

    @property
    def present(self) -> bool:
        return self.over_cap or self.value is not None


@frozen
class PreviewEventValues:
    uuid: str
    event: str
    values: dict[str, StoredValue]


def _field(name: str) -> ast.Field:
    return ast.Field(chain=[name])


def _call(name: str, *args: ast.Expr) -> ast.Call:
    return ast.Call(name=name, args=list(args))


def _compare(op: ast.CompareOperationOp, left: ast.Expr, right: ast.Expr) -> ast.CompareOperation:
    return ast.CompareOperation(op=op, left=left, right=right)


def _over_cap(value: ast.Expr) -> ast.Expr:
    return _compare(ast.CompareOperationOp.Gt, _call("length", value), ast.Constant(value=PREVIEW_SOURCE_MAX_BYTES))


def _capped(value: ast.Expr) -> ast.Expr:
    return _call("if", _over_cap(value), ast.Constant(value=None), value)


def _raw(column: str) -> ast.Expr:
    # The JSON array functions cannot return a Nullable array, so a missing value is read as an empty string.
    return _call("ifNull", _field(column), ast.Constant(value=""))


def _tail_items(tail: int) -> ast.Expr:
    return _call("arraySlice", _call("JSONExtractArrayRaw", _raw("input")), ast.Constant(value=-tail))


def _per_tail_item(expr: ast.Expr, tail: int) -> ast.Expr:
    return _call("arrayMap", ast.Lambda(args=["item"], expr=expr), _tail_items(tail))


def _input_tail_over_caps(tail: int) -> ast.Expr:
    return _per_tail_item(_over_cap(_field("item")), tail)


def _input_tail(tail: int) -> ast.Expr:
    # An oversized item is replaced rather than dropped, so the positions stay aligned with its over-cap flags.
    item = _field("item")
    kept_items = _per_tail_item(_call("if", _over_cap(item), ast.Constant(value="null"), item), tail)
    joined = _call(
        "concat",
        ast.Constant(value="["),
        _call("arrayStringConcat", kept_items, ast.Constant(value=",")),
        ast.Constant(value="]"),
    )
    is_list = _compare(ast.CompareOperationOp.Eq, _call("JSONType", _raw("input")), ast.Constant(value="Array"))
    return _call("if", is_list, joined, _capped(_field("input")))


def _for(event_ids: Sequence[str], expr: ast.Expr, otherwise: ast.Expr) -> ast.Expr:
    if not event_ids:
        return otherwise
    return _call("if", column_in("uuid", event_ids), expr, otherwise)


def _read_for(reads: PreviewReads) -> dict[str, Sequence[str]]:
    return {
        "$ai_input": reads.input_ids,
        "$ai_output_choices": reads.output_ids,
        "$ai_output": reads.output_ids,
        "$ai_input_state": reads.state_ids,
        "$ai_output_state": reads.state_ids,
    }


def _values_select(reads: PreviewReads, tail: int) -> list[ast.Expr]:
    read_for = _read_for(reads)
    selected: list[ast.Expr] = [
        _field("uuid"),
        _field("event"),
        ast.Alias(
            alias="input_item_over_caps",
            expr=_for(read_for[_TAIL_PROPERTY], _input_tail_over_caps(tail), ast.Array(exprs=[])),
        ),
    ]
    for name, column in _COLUMNS.items():
        value = _input_tail(tail) if name == _TAIL_PROPERTY else _capped(_field(column))
        # An alias named like its column would shadow the column in the over-cap check.
        selected += [
            ast.Alias(alias=f"{column}_value", expr=_for(read_for[name], value, ast.Constant(value=None))),
            ast.Alias(
                alias=f"{column}_over_cap",
                expr=_for(read_for[name], _over_cap(_field(column)), ast.Constant(value=False)),
            ),
        ]
    return selected


def _events_query(trace_ids: Sequence[str], where: ast.Expr, has_state: ast.Expr, *, latest: bool) -> ast.SelectQuery:
    # The earliest and the latest event of each name, and of each state for trace events, are all the picks choose
    # from, so a trace reads at most a few light rows however long it is.
    return ast.SelectQuery(
        select=[
            *(_field(column) for column in _EVENT_COLUMNS[:-1]),
            ast.Alias(alias="has_state", expr=clone_expr(has_state)),
        ],
        select_from=ai_events(),
        where=where,
        order_by=[
            ast.OrderExpr(expr=_field("timestamp"), order="DESC" if latest else "ASC"),
            ast.OrderExpr(expr=_field("uuid"), order="ASC"),
        ],
        limit_by=ast.LimitByExpr(
            n=ast.Constant(value=1), exprs=[_field("trace_id"), _field("event"), _field("has_state")]
        ),
        limit=ast.Constant(value=len(trace_ids) * len(_PICKED_EVENT_NAMES) * 2),
    )


def _picks_query(trace_ids: Sequence[str], where: ast.Expr, has_state: ast.Expr) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[_field(column) for column in _EVENT_COLUMNS],
        select_from=ast.JoinExpr(
            table=ast.SelectSetQuery.create_from_queries(
                [
                    _events_query(trace_ids, where, has_state, latest=False),
                    _events_query(trace_ids, where, has_state, latest=True),
                ],
                "UNION ALL",
            )
        ),
    )


def _values_query(reads: PreviewReads, tail: int, where: ast.Expr) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=_values_select(reads, tail),
        select_from=ai_events(),
        where=where,
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[_field("uuid")]),
        limit=ast.Constant(value=len(reads.event_ids)),
    )


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_PREVIEW_QUERY_SECONDS, timeout_overflow_mode="throw")


def _parsed(raw: Any) -> Value:
    return None if raw is None or raw == "" else parse_ai_property_value(raw)


def _picked_events_where(trace_ids: Sequence[str], window: FallbackWindow | None) -> ast.Expr:
    trace_filter = column_in("trace_id", trace_ids)
    event_filter = event_in(_PICKED_EVENT_NAMES)
    if window is None:
        return ast.And(exprs=[trace_filter, event_filter])
    return events_filter(trace_filter=trace_filter, event_filter=event_filter, window=window)


def _values_where(reads: PreviewReads, window: FallbackWindow | None) -> ast.Expr:
    trace_and_event = ast.And(exprs=[column_in("trace_id", reads.trace_ids), column_in("uuid", reads.event_ids)])
    if window is None:
        return trace_and_event
    return events_filter(trace_filter=trace_and_event, event_filter=event_in(_PICKED_EVENT_NAMES), window=window)


def _read(
    name: str,
    query: ast.SelectQuery,
    team: Team,
    user: User | None,
    window: FallbackWindow | None,
) -> list[Any]:
    read = read_ai_events_table if window is None else read_shared_events_table
    return read(name, query, team, user, _settings())


def load_preview_event_rows(
    team: Team,
    user: User | None,
    trace_ids: Sequence[str],
    *,
    window: FallbackWindow | None = None,
    name: str = PREVIEW_PICKS_QUERY_NAME,
) -> list[PreviewEventRow]:
    """The light rows the picks choose from. With a `window`, reads the shared events table inside it instead of
    `posthog.ai_events`."""
    query = _picks_query(
        trace_ids,
        _picked_events_where(trace_ids, window),
        AI_EVENTS_HAS_STATE if window is None else EVENTS_HAS_STATE,
    )
    return [
        PreviewEventRow(
            trace_id=str(trace_id),
            uuid=str(uuid),
            event=str(event),
            timestamp=timestamp,
            has_state=read_flag(has_state),
        )
        for trace_id, uuid, event, timestamp, has_state in _read(name, query, team, user, window)
    ]


def load_preview_values(
    team: Team,
    user: User | None,
    reads: PreviewReads,
    *,
    window: FallbackWindow | None = None,
    name: str = PREVIEWS_QUERY_NAME,
    tail: int = TURN_INPUT_TAIL,
) -> dict[str, PreviewEventValues]:
    if not reads.event_ids:
        return {}
    results = _read(name, _values_query(reads, tail, _values_where(reads, window)), team, user, window)
    rows = (
        PreviewEventValues(
            uuid=str(uuid),
            event=str(event),
            values={
                name: StoredValue(
                    value=_parsed(value),
                    over_cap=read_flag(over_cap),
                    item_over_caps=tuple(read_flag(flag) for flag in item_over_caps)
                    if name == _TAIL_PROPERTY
                    else None,
                )
                for name, value, over_cap in zip(_COLUMNS, columns[::2], columns[1::2])
            },
        )
        for uuid, event, item_over_caps, *columns in results
    )
    return {row.uuid: row for row in rows}


def load_preview_sources(team: Team, user: User | None, trace_ids: Sequence[str]) -> dict[str, TracePreviewSources]:
    """The values each trace's preview is built from, keyed by trace id. A trace with no state event and no
    generation has no entry. Reads only `posthog.ai_events`, so a trace past its retention there has none either."""
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    rows = load_preview_event_rows(team, user, requested)
    picks = pick_preview_events(rows)
    try:
        values = load_preview_values(team, user, PreviewReads.of(picks))
    except (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong):
        return timed_out_sources(picks, rows)
    return preview_sources(picks, values)
