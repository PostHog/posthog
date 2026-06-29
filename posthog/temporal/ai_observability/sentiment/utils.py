"""Utility helpers for sentiment classification."""

from typing import Any

from posthog.temporal.ai_observability.sentiment.schema import PendingClassification


def average_score_dicts(score_dicts: list[dict[str, float]]) -> dict[str, float]:
    """Average a list of {label: score} dicts."""
    if not score_dicts:
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    labels = ["positive", "neutral", "negative"]
    n = len(score_dicts)
    return {label: round(sum(d.get(label, 0.0) for d in score_dicts) / n, 4) for label in labels}


def build_generation_result(
    gen_uuid: str,
    pending: list[PendingClassification],
    classification_results: list,
) -> dict[str, Any]:
    """Build a single generation's sentiment dict from classified pending items.

    Returns {label, score, scores, messages, message_count}.
    """
    gen_pending = [p for p in pending if p.gen_uuid == gen_uuid]
    gen_results = classification_results[: len(gen_pending)]

    if not gen_pending:
        return {
            "label": "neutral",
            "score": 0.0,
            "scores": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
            "messages": {},
            "message_count": 0,
        }

    messages: dict[str, dict[str, Any]] = {}
    all_scores: list[dict[str, float]] = []

    for item, result in zip(gen_pending, gen_results):
        msg_dict = {
            "label": result.label,
            "score": result.score,
            "scores": result.scores,
        }
        messages[str(item.msg_index)] = msg_dict
        all_scores.append(result.scores)

    gen_scores = average_score_dicts(all_scores)
    gen_label = max(gen_scores, key=gen_scores.get)  # type: ignore

    return {
        "label": gen_label,
        "score": gen_scores[gen_label],
        "scores": gen_scores,
        "messages": messages,
        "message_count": len(gen_pending),
    }
