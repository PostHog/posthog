from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import orjson

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events

if TYPE_CHECKING:
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.modifiers import HogQLQueryModifiers
    from posthog.hogql.timings import HogQLTimings

    from posthog.models import Team


SentimentMessage = dict[str, Any]
SentimentResult = dict[str, Any]

AI_EVENTS_GENERATION_SENTIMENT_GENERATION_ID_SELECT = "ifNull(nullIf(nullIf(toString(generation_id), ''), 'null'), '')"
MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE = 1000
SENTIMENT_LABELS = ("positive", "neutral", "negative")


@dataclass(frozen=True)
class SentimentEvaluationLookup:
    by_trace_id: dict[str, SentimentResult]
    by_generation_id: dict[str, SentimentResult]


EMPTY_SENTIMENT_EVALUATION_LOOKUP = SentimentEvaluationLookup(by_trace_id={}, by_generation_id={})


def get_generation_sentiment_lookup_ids(
    event_id: str,
    event_name: str,
    properties: Mapping[str, object] | None,
) -> list[str]:
    ids = [event_id] if event_id else []
    if event_name != "$ai_generation" or properties is None:
        return ids

    generation_id = _normalize_lookup_id(properties.get("$ai_generation_id"))
    if generation_id:
        ids.append(generation_id)

    return dedupe_non_empty(ids)


def get_sentiment_for_generation(
    lookup: SentimentEvaluationLookup,
    generation_ids: Sequence[str],
) -> SentimentResult | None:
    for generation_id in generation_ids:
        sentiment = lookup.by_generation_id.get(generation_id)
        if sentiment is not None:
            return sentiment
    return None


_SENTIMENT_EVALUATIONS_SQL = """
SELECT
    trace_id,
    toString(properties.$ai_target_event_id) AS generation_id,
    argMax(toString(properties.$ai_sentiment_label), timestamp) AS label,
    argMax(toString(properties.$ai_sentiment_score), timestamp) AS score,
    argMax(properties.$ai_sentiment_scores, timestamp) AS scores,
    argMax(properties.$ai_sentiment_messages, timestamp) AS messages,
    argMax(toString(properties.$ai_sentiment_message_count), timestamp) AS message_count
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_evaluation'
  AND properties.$ai_evaluation_runtime = 'sentiment'
  AND trace_id IN {trace_ids}
  AND length(toString(properties.$ai_target_event_id)) > 0
  AND {generation_filter}
GROUP BY trace_id, toString(properties.$ai_target_event_id)
LIMIT {limit}
"""

_TRACE_SENTIMENT_EVALUATIONS_SQL = """
SELECT
    trace_id,
    groupArray(tuple(generation_id, label, score, scores, messages, message_count)) AS generation_results
FROM (
    SELECT
        trace_id,
        toString(properties.$ai_target_event_id) AS generation_id,
        argMax(toString(properties.$ai_sentiment_label), timestamp) AS label,
        argMax(toString(properties.$ai_sentiment_score), timestamp) AS score,
        argMax(properties.$ai_sentiment_scores, timestamp) AS scores,
        argMax(properties.$ai_sentiment_messages, timestamp) AS messages,
        argMax(toString(properties.$ai_sentiment_message_count), timestamp) AS message_count
    FROM posthog.ai_events AS ai_events
    WHERE event = '$ai_evaluation'
      AND properties.$ai_evaluation_runtime = 'sentiment'
      AND trace_id IN {trace_ids}
      AND length(toString(properties.$ai_target_event_id)) > 0
    GROUP BY trace_id, toString(properties.$ai_target_event_id)
)
GROUP BY trace_id
LIMIT {limit}
"""


def load_generation_sentiment_evaluations_for_traces(
    *,
    team: Team,
    trace_ids: Sequence[str],
    generation_ids: Sequence[str] | None = None,
    timings: HogQLTimings | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    limit_context: LimitContext | None = None,
    query_type: str = "LLMGenerationSentimentEvaluations",
) -> SentimentEvaluationLookup:
    unique_trace_ids = dedupe_non_empty(trace_ids)
    if not unique_trace_ids:
        return EMPTY_SENTIMENT_EVALUATION_LOOKUP

    unique_generation_ids = dedupe_non_empty(generation_ids or [])
    generation_filter: ast.Expr = ast.Constant(value=True)
    if unique_generation_ids:
        generation_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["properties", "$ai_target_event_id"]),
            right=ast.Tuple(exprs=[ast.Constant(value=generation_id) for generation_id in unique_generation_ids]),
        )

    query = parse_select(_SENTIMENT_EVALUATIONS_SQL)
    result = query_ai_events(
        query=query,
        placeholders={
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=trace_id) for trace_id in unique_trace_ids]),
            "generation_filter": generation_filter,
            "limit": ast.Constant(
                value=max(
                    len(unique_trace_ids) * MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE,
                    len(unique_generation_ids),
                    1,
                )
            ),
        },
        team=team,
        query_type=query_type,
        fall_back_to_events=True,
        timings=timings,
        modifiers=modifiers,
        limit_context=limit_context,
    )

    by_trace_generation: dict[str, list[tuple[str, SentimentResult]]] = {}
    by_generation_id: dict[str, SentimentResult] = {}

    for row in result.results or []:
        trace_id, generation_id, label, score, scores, messages, message_count = row
        normalized = normalize_sentiment_result(label, score, scores, messages, message_count)

        trace_id = str(trace_id)
        generation_id = str(generation_id)
        by_generation_id[generation_id] = normalized
        by_trace_generation.setdefault(trace_id, []).append((generation_id, normalized))

    return SentimentEvaluationLookup(
        by_trace_id={
            trace_id: _aggregate_trace_sentiment(generation_results)
            for trace_id, generation_results in by_trace_generation.items()
        },
        by_generation_id=by_generation_id,
    )


def load_trace_sentiment_evaluations(
    *,
    team: Team,
    trace_ids: Sequence[str],
    timings: HogQLTimings | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    limit_context: LimitContext | None = None,
    query_type: str = "LLMTraceSentimentEvaluations",
) -> dict[str, SentimentResult]:
    unique_trace_ids = dedupe_non_empty(trace_ids)
    if not unique_trace_ids:
        return {}

    query = parse_select(_TRACE_SENTIMENT_EVALUATIONS_SQL)
    result = query_ai_events(
        query=query,
        placeholders={
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=trace_id) for trace_id in unique_trace_ids]),
            "limit": ast.Constant(value=len(unique_trace_ids)),
        },
        team=team,
        query_type=query_type,
        fall_back_to_events=True,
        timings=timings,
        modifiers=modifiers,
        limit_context=limit_context,
    )

    by_trace_id: dict[str, SentimentResult] = {}
    for row in result.results or []:
        trace_id, generation_results = row
        normalized_generation_results: list[tuple[str, SentimentResult]] = []
        for generation_result in generation_results or []:
            if not isinstance(generation_result, list | tuple) or len(generation_result) < 6:
                continue
            generation_id, label, score, scores, messages, message_count = generation_result[:6]
            normalized_generation_results.append(
                (
                    str(generation_id),
                    normalize_sentiment_result(label, score, scores, messages, message_count),
                )
            )

        if normalized_generation_results:
            by_trace_id[str(trace_id)] = _aggregate_trace_sentiment(normalized_generation_results)

    return by_trace_id


def dedupe_non_empty(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalize_lookup_id(value: object) -> str | None:
    if value is None:
        return None

    value_string = value if isinstance(value, str) else str(value)
    if not value_string or value_string == "null":
        return None
    return value_string


def normalize_sentiment_result(
    label: object,
    score: object,
    scores: object,
    messages: object,
    message_count: object,
) -> SentimentResult:
    label_value = _normalize_label(label)
    scores_value = _normalize_scores(scores)
    messages_value = _normalize_messages(messages)
    score_value = _normalize_float(score)

    if score_value is None:
        score_value = scores_value.get(label_value, 0.0)

    return {
        "label": label_value,
        "score": score_value,
        "scores": scores_value,
        "messages": messages_value,
        "message_count": _normalize_int(message_count) or len(messages_value),
    }


def _aggregate_trace_sentiment(generation_results: list[tuple[str, SentimentResult]]) -> SentimentResult:
    flat_messages: dict[str, SentimentMessage] = {}
    score_dicts: list[dict[str, float]] = []

    for generation_id, result in generation_results:
        messages = result.get("messages")
        if isinstance(messages, dict) and messages:
            message_score_dicts: list[dict[str, float]] = []
            for message_index, message in messages.items():
                if not isinstance(message, dict):
                    continue
                flat_messages[f"{generation_id}:{message_index}"] = message
                message_scores = _score_dict_from_sentiment(message)
                if message_scores is not None:
                    message_score_dicts.append(message_scores)
            if message_score_dicts:
                score_dicts.extend(message_score_dicts)
                continue

        result_scores = _score_dict_from_sentiment(result)
        if result_scores is not None:
            score_dicts.append(result_scores)

    scores = _average_score_dicts(score_dicts)
    label = (
        max(SENTIMENT_LABELS, key=lambda sentiment_label: scores.get(sentiment_label, 0.0))
        if _has_score_signal(scores)
        else "neutral"
    )
    return {
        "label": label,
        "score": scores[label],
        "scores": scores,
        "messages": flat_messages,
        "message_count": len(flat_messages),
    }


def _decode_jsonish(value: object) -> object:
    if isinstance(value, dict | list):
        return value
    if isinstance(value, bytes):
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        if not value:
            return None
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return value
    return value


def _normalize_label(value: object) -> str:
    if isinstance(value, str) and value in SENTIMENT_LABELS:
        return value
    return "neutral"


def _normalize_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalize_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _normalize_scores(value: object) -> dict[str, float]:
    decoded = _decode_jsonish(value)
    if not isinstance(decoded, dict):
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    return {
        "positive": _normalize_float(decoded.get("positive")) or 0.0,
        "neutral": _normalize_float(decoded.get("neutral")) or 0.0,
        "negative": _normalize_float(decoded.get("negative")) or 0.0,
    }


def _normalize_messages(value: object) -> dict[str, SentimentMessage]:
    decoded = _decode_jsonish(value)
    if not isinstance(decoded, dict):
        return {}

    messages: dict[str, SentimentMessage] = {}
    for key, raw_message in decoded.items():
        if not isinstance(raw_message, dict):
            continue

        messages[str(key)] = {
            "label": _normalize_label(raw_message.get("label")),
            "score": _normalize_float(raw_message.get("score")) or 0.0,
            "scores": _normalize_scores(raw_message.get("scores")),
        }

    return messages


def _score_dict_from_sentiment(value: Mapping[str, object]) -> dict[str, float] | None:
    scores = _normalize_scores(value.get("scores"))
    if _has_score_signal(scores):
        return scores

    score = _normalize_float(value.get("score"))
    if score is None or score == 0.0:
        return None

    label = _normalize_label(value.get("label"))
    return {sentiment_label: score if sentiment_label == label else 0.0 for sentiment_label in SENTIMENT_LABELS}


def _has_score_signal(scores: Mapping[str, float]) -> bool:
    return any(score != 0.0 for score in scores.values())


def _average_score_dicts(score_dicts: list[dict[str, float]]) -> dict[str, float]:
    if not score_dicts:
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    return {
        label: round(sum(scores.get(label, 0.0) for scores in score_dicts) / len(score_dicts), 4)
        for label in SENTIMENT_LABELS
    }
