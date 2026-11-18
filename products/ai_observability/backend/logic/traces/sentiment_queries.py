from collections.abc import Sequence
from datetime import datetime
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
from .events_fallback import FallbackWindow
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


def _sentiments_query(trace_count: int) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Alias(alias=alias, expr=expr) for alias, expr in _COLUMNS.items()],
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
        order_by=[
            ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["uuid"]), order="DESC"),
        ],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["trace_id"]), _GENERATION_ID]),
        limit=ast.Constant(value=trace_count * MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE),
    )


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_SENTIMENT_QUERY_SECONDS)


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
    # have lost rows reads the shared events table.
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
                events_placeholders(column_in("trace_id", missing), (_EVALUATION_EVENT,), window),
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
        for trace_id, generation_id, label, score, scores, messages, message_count in results
    ]


def _trace_sentiment(results: list[tuple[str, SentimentResult]]) -> TraceSentimentRow:
    sentiment = aggregate_trace_sentiment(results)
    return TraceSentimentRow(label=_LABELS[sentiment["label"]], score=float(sentiment["score"]))


def load_sentiments(
    team: Team, user: User | None, trace_ids: Sequence[str], window: FallbackWindow, now: datetime
) -> dict[str, TraceSentimentRow]:
    """The sentiment of each trace that has one, keyed by trace id, from the latest result per generation. When the
    window starts before `posthog.ai_events` may have dropped rows, traces with no result there are read from the shared
    events table inside the window."""
    requested = list(dict.fromkeys(trace_ids))
    if not requested:
        return {}
    by_trace: dict[str, list[tuple[str, SentimentResult]]] = {}
    for row in _read_rows(team, user, requested, window, now):
        # Matches the sentiment loader in posthog/hogql_queries/ai/sentiment_evaluations.py, which drops a generation
        # whose latest result counted no messages.
        if row.message_count == "0":
            continue
        by_trace.setdefault(row.trace_id, []).append(
            (
                row.generation_id,
                normalize_sentiment_result(row.label, row.score, row.scores, row.messages, row.message_count),
            )
        )
    return {trace_id: _trace_sentiment(results) for trace_id, results in by_trace.items()}
