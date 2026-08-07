"""Shared sentiment label selection.

Used both when writing evaluations (the sentiment eval activity) and when
aggregating them on read (trace sentiment), so a low-confidence polar score
resolves to neutral consistently on both sides. Kept here, off the temporal
package, so the read path doesn't drag the AI-observability workflow graph.
"""

# A polar label (negative/positive) must beat neutral by more than this margin to be
# assigned; otherwise the message is treated as neutral. Short, task-focused messages
# often split near-evenly between neutral and a polar label, and promoting those
# coin-flips to negative/positive is the main source of false polar labels.
SENTIMENT_NEUTRAL_MARGIN = 0.15


def select_sentiment_label(scores: dict[str, float], neutral_margin: float = SENTIMENT_NEUTRAL_MARGIN) -> str:
    """Pick a sentiment label, keeping low-confidence polar calls in neutral.

    Returns the top-scoring label, except when it is a polar label (negative/positive)
    that does not beat neutral by more than `neutral_margin` — those near-ties (and exact
    ties at the margin) resolve to neutral rather than being promoted to a polar label the
    model is barely confident about. The gap is rounded to the 4 decimals the scores already
    carry, so the boundary decision doesn't hinge on floating-point error.
    """
    top_label = max(scores, key=scores.get)  # type: ignore
    if top_label == "neutral":
        return "neutral"
    if round(scores[top_label] - scores.get("neutral", 0.0), 4) <= neutral_margin:
        return "neutral"
    return top_label
