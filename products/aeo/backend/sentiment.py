"""How an answer engine's reply speaks about the brand.

Only the sentences that name the brand are scored, so praise of a competitor in
the same answer does not count as praise of the brand. The classifier itself is
the AI observability ONNX model; it lives on the evals Temporal queue, and this
module only prepares its input and folds its output back into one label per answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.sentiment_labeling import select_sentiment_label

from products.aeo.backend.brand import brand_pattern

SENTIMENT_LABELS = ("negative", "neutral", "positive")
# Bounds the classifier input per answer: an answer that names the brand in more sentences than
# this is scored on the first ones, and the model truncates a sentence longer than this anyway.
MAX_BRAND_SENTENCES = 20
MAX_SENTENCE_CHARS = 1000
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


@frozen
class AnswerSentiment:
    label: str
    score: float


def brand_sentences(answer_text: str | None, target_domains: list[str]) -> list[str]:
    """The sentences of an answer that name the brand, in order, trimmed and bounded."""
    pattern = brand_pattern(target_domains)
    if not answer_text or pattern is None:
        return []
    sentences = (sentence.strip() for sentence in _SENTENCE_BREAK.split(answer_text))
    matching = (sentence[:MAX_SENTENCE_CHARS] for sentence in sentences if sentence and pattern.search(sentence))
    return [sentence for _, sentence in zip(range(MAX_BRAND_SENTENCES), matching)]


def aggregate_sentiment(sentence_scores: Sequence[Mapping[str, float]]) -> AnswerSentiment | None:
    """One label for the answer from its brand sentences' class scores.

    The class scores are averaged over the sentences before the label is picked, so one strongly
    negative sentence among neutral ones pulls the answer toward negative without a majority vote
    flipping it, and the same neutral margin as AI observability keeps near-ties neutral."""
    if not sentence_scores:
        return None
    mean_scores = {
        label: round(sum(scores.get(label, 0.0) for scores in sentence_scores) / len(sentence_scores), 4)
        for label in SENTIMENT_LABELS
    }
    label = select_sentiment_label(mean_scores)
    return AnswerSentiment(label=label, score=mean_scores[label])
