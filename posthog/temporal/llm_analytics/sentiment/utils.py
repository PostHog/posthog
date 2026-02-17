"""Utility helpers for sentiment classification."""

from datetime import UTC, timedelta
from typing import Any

from posthog.temporal.llm_analytics.sentiment.schema import PendingClassification, empty_trace_result


def average_scores(message_results: list[dict[str, Any]]) -> dict[str, float]:
    """Average softmax scores across message results."""
    score_dicts = [m["scores"] for m in message_results]
    return average_score_dicts(score_dicts)


def average_score_dicts(score_dicts: list[dict[str, float]]) -> dict[str, float]:
    """Average a list of {label: score} dicts."""
    if not score_dicts:
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    labels = ["positive", "neutral", "negative"]
    n = len(score_dicts)
    return {label: round(sum(d.get(label, 0.0) for d in score_dicts) / n, 4) for label in labels}


def build_trace_result(
    trace_id: str,
    pending: list[PendingClassification],
    classification_results: list,
    pending_offset: int,
) -> tuple[dict[str, Any], int]:
    """Build a single trace's sentiment result from classified pending items.

    Returns (result_dict, count_consumed) where count_consumed is how many
    items from classification_results were used.
    """
    trace_pending = [p for p in pending if p.trace_id == trace_id]
    trace_results = classification_results[pending_offset : pending_offset + len(trace_pending)]

    if not trace_pending:
        return empty_trace_result(trace_id), 0

    gen_messages: dict[str, dict[int, dict[str, Any]]] = {}
    all_scores: list[dict[str, float]] = []

    for item, result in zip(trace_pending, trace_results):
        msg_dict = {
            "label": result.label,
            "score": result.score,
            "scores": result.scores,
        }
        gen_messages.setdefault(item.gen_uuid, {})[item.msg_index] = msg_dict
        all_scores.append(result.scores)

    generations: dict[str, Any] = {}
    for gen_uuid, msgs in gen_messages.items():
        gen_scores = average_scores(list(msgs.values()))
        gen_label = max(gen_scores, key=gen_scores.get)  # type: ignore
        generations[gen_uuid] = {
            "label": gen_label,
            "score": gen_scores[gen_label],
            "scores": gen_scores,
            "messages": msgs,
        }

    trace_scores = average_score_dicts(all_scores)
    trace_label = max(trace_scores, key=trace_scores.get)  # type: ignore

    return {
        "trace_id": trace_id,
        "label": trace_label,
        "score": round(trace_scores[trace_label], 4),
        "scores": trace_scores,
        "generations": generations,
        "generation_count": len(generations),
        "message_count": len(trace_pending),
    }, len(trace_pending)


def collect_pending(
    generations: list[tuple[str, dict]],
    trace_id: str,
    cap: int,
) -> list[PendingClassification]:
    """Parse generation rows and collect user messages for classification."""
    from posthog.temporal.llm_analytics.sentiment.extraction import (
        extract_user_messages_individually,
        truncate_to_token_limit,
    )

    pending: list[PendingClassification] = []

    for event_uuid, props in generations:
        user_messages = extract_user_messages_individually(props.get("$ai_input"))
        if not user_messages:
            continue

        for original_index, msg_text in user_messages:
            if len(pending) >= cap:
                break
            pending.append(
                PendingClassification(
                    trace_id=trace_id,
                    gen_uuid=event_uuid,
                    msg_index=original_index,
                    text=truncate_to_token_limit(msg_text),
                )
            )

        if len(pending) >= cap:
            break

    return pending


def resolve_date_bounds(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Resolve caller-provided date strings to concrete timestamps for the query.

    Handles relative date strings (e.g. "-1h", "-7d") by converting them to
    absolute timestamps via `relative_date_parse`. Falls back to a lookback
    window when no bounds are provided.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from posthog.temporal.llm_analytics.sentiment.constants import QUERY_LOOKBACK_DAYS
    from posthog.utils import relative_date_parse

    now = datetime.now(tz=UTC)
    fmt = "%Y-%m-%d %H:%M:%S"

    if date_from:
        try:
            resolved_from = relative_date_parse(date_from, ZoneInfo("UTC"), now=now).strftime(fmt)
        except Exception:
            resolved_from = (now - timedelta(days=QUERY_LOOKBACK_DAYS)).strftime(fmt)
    else:
        resolved_from = (now - timedelta(days=QUERY_LOOKBACK_DAYS)).strftime(fmt)

    if date_to:
        try:
            resolved_to = relative_date_parse(date_to, ZoneInfo("UTC"), now=now).strftime(fmt)
        except Exception:
            resolved_to = now.strftime(fmt)
    else:
        resolved_to = now.strftime(fmt)

    return resolved_from, resolved_to
