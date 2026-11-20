from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import get_args

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.sentiment_evaluations import (
    MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE,
    SentimentResult,
    aggregate_trace_sentiment,
    normalize_sentiment_result,
)
from posthog.models import Team, User

from ...facade.contracts import TraceSentimentLabel
from .events_fallback import AI_EVENTS_RETENTION_DAYS, FallbackWindow
from .trace_queries import (
    ai_events,
    ai_events_placeholders,
    column_in,
    equals,
    events_placeholders,
    filter_conditions,
    read_ai_events_table,
    read_shared_events_table,
)

SENTIMENT_QUERY_NAME = "ai_traces_sentiment"
_SENTIMENT_QUERY_SECONDS = 15
_EVALUATION_EVENT = "$ai_evaluation"
_LABELS: dict[str, TraceSentimentLabel] = {label: label for label in get_args(TraceSentimentLabel)}


@frozen
class TraceSentimentRow:
    label: TraceSentimentLabel
    score: float


@frozen
class _GenerationSentimentRow:
    trace_id: str
    generation_id: str
    label: object
    score: object
    scores: object
    messages: object
    message_count: object


def _property(name: str) -> ast.Field:
    return ast.Field(chain=["properties", name])


def _text(name: str) -> ast.Call:
    return ast.Call(name="toString", args=[_property(name)])


_GENERATION_ID = _text("$ai_target_event_id")
_COLUMNS: dict[str, ast.Expr] = {
    "trace_id": ast.Field(chain=["trace_id"]),
    "generation_id": _GENERATION_ID,
    "label": _text("$ai_sentiment_label"),
    "score": _text("$ai_sentiment_score"),
    "scores": _property("$ai_sentiment_scores"),
    "messages": _property("$ai_sentiment_messages"),
    "message_count": _text("$ai_sentiment_message_count"),
}


def _newest_first() -> list[ast.OrderExpr]:
    return [
        ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC"),
        ast.OrderExpr(expr=ast.Field(chain=["uuid"]), order="DESC"),
    ]


def _sentiments_query(trace_count: int) -> ast.SelectQuery:
    latest_per_generation = ast.SelectQuery(
        select=[
            *(ast.Alias(alias=alias, expr=expr) for alias, expr in _COLUMNS.items()),
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["uuid"]),
        ],
        select_from=ai_events(),
        where=ast.And(
            exprs=[
                equals("event", _EVALUATION_EVENT),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=_property("$ai_evaluation_runtime"),
                    right=ast.Constant(value="sentiment"),
                ),
                ast.Call(name="notEmpty", args=[_GENERATION_ID]),
                filter_conditions(),
            ]
        ),
        order_by=_newest_first(),
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["trace_id"]), _GENERATION_ID]),
    )
    # HogQL takes one LIMIT BY per query, so each generation's latest result is picked, and a result that counted no
    # messages dropped, before the per-trace cap.
    capped_per_trace = ast.SelectQuery(
        select=[ast.Field(chain=[alias]) for alias in _COLUMNS],
        select_from=ast.JoinExpr(table=latest_per_generation),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["message_count"]), right=ast.Constant(value="0")
        ),
        order_by=_newest_first(),
        limit_by=ast.LimitByExpr(
            n=ast.Constant(value=MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE), exprs=[ast.Field(chain=["trace_id"])]
        ),
    )
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["trace_id"]),
            ast.Call(
                name="groupArray",
                args=[ast.Tuple(exprs=[ast.Field(chain=[alias]) for alias in _COLUMNS if alias != "trace_id"])],
            ),
        ],
        select_from=ast.JoinExpr(table=capped_per_trace),
        group_by=[ast.Field(chain=["trace_id"])],
        limit=ast.Constant(value=trace_count),
    )


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_SENTIMENT_QUERY_SECONDS)


def _fallback_end(window: FallbackWindow, now: datetime) -> datetime:
    # A generation cannot be evaluated after it leaves `posthog.ai_events`. Compared before adding, because a window
    # that ends near the last datetime would overflow.
    evaluable_for = timedelta(days=AI_EVENTS_RETENTION_DAYS + 1)
    return now if window.end >= now - evaluable_for else window.end + evaluable_for


def _read_rows(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow, now: datetime
) -> list[_GenerationSentimentRow]:
    results = read_ai_events_table(
        SENTIMENT_QUERY_NAME,
        _sentiments_query(len(trace_ids)),
        team,
        user,
        _settings(),
        ai_events_placeholders(column_in("trace_id", trace_ids)),
    )
    # A trace with no sentiment result looks the same as one whose results aged out, so only a page old enough to
    # have lost rows reads the shared events table. That read reaches past the window's end, because a manual run
    # stamps its results with the time it ran, but only until the window's generations have left ai_events, because
    # a generation can only be evaluated while it is there.
    if window.may_hold_aged_out_events(now):
        found = {str(row[0]) for row in results}
        missing = [trace_id for trace_id in trace_ids if trace_id not in found]
        if missing:
            results += read_shared_events_table(
                SENTIMENT_QUERY_NAME,
                _sentiments_query(len(missing)),
                team,
                user,
                _settings(),
                events_placeholders(
                    column_in("trace_id", missing),
                    (_EVALUATION_EVENT,),
                    FallbackWindow(
                        start=window.start,
                        end=_fallback_end(window, now),
                    ),
                ),
            )
    return [
        _GenerationSentimentRow(
            trace_id=str(trace_id),
            generation_id=str(generation_id),
            label=label,
            score=score,
            scores=scores,
            messages=messages,
            message_count=message_count,
        )
        for trace_id, generations in results
        for generation_id, label, score, scores, messages, message_count in generations
    ]


def _trace_sentiment(results: list[tuple[str, SentimentResult]]) -> TraceSentimentRow:
    sentiment = aggregate_trace_sentiment(results)
    return TraceSentimentRow(label=_LABELS[sentiment["label"]], score=float(sentiment["score"]))


def load_sentiments(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow, now: datetime
) -> dict[str, TraceSentimentRow]:
    """The sentiment of each trace that has one, keyed by trace id, from the latest result per generation. When the
    window starts before `posthog.ai_events` may have dropped rows, traces with no result there are read from the shared
    events table from the window's start until its generations leave `posthog.ai_events`, or `now` if that is sooner."""
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    by_trace: dict[str, list[tuple[str, SentimentResult]]] = {}
    for row in _read_rows(team, user, requested, window, now):
        by_trace.setdefault(row.trace_id, []).append(
            (
                row.generation_id,
                normalize_sentiment_result(row.label, row.score, row.scores, row.messages, row.message_count),
            )
        )
    return {trace_id: _trace_sentiment(results) for trace_id, results in by_trace.items()}
