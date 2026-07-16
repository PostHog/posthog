"""Utility helpers for sentiment classification."""

from typing import Any

from posthog.temporal.ai_observability.sentiment.constants import SENTIMENT_NEUTRAL_MARGIN
from posthog.temporal.ai_observability.sentiment.schema import PendingClassification


def select_sentiment_label(scores: dict[str, float], neutral_margin: float = SENTIMENT_NEUTRAL_MARGIN) -> str:
    """Pick a sentiment label, keeping low-confidence polar calls in neutral.

    Returns the top-scoring label, except when it is a polar label (negative/positive)
    that fails to beat neutral by `neutral_margin` — those near-ties resolve to neutral
    rather than being promoted to a polar label the model is barely confident about.
    """
    top_label = max(scores, key=scores.get)  # type: ignore
    if top_label == "neutral":
        return "neutral"
    if scores[top_label] - scores.get("neutral", 0.0) < neutral_margin:
        return "neutral"
    return top_label


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
            "text": item.text,
        }
        messages[str(item.msg_index)] = msg_dict
        all_scores.append(result.scores)

    gen_scores = average_score_dicts(all_scores)
    gen_label = select_sentiment_label(gen_scores)

    return {
        "label": gen_label,
        "score": gen_scores[gen_label],
        "scores": gen_scores,
        "messages": messages,
        "message_count": len(gen_pending),
    }
