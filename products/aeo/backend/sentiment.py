"""How an answer engine's reply speaks about the brand.

Only the sentences that name the brand are scored, so praise of a competitor in
the same answer does not count as praise of the brand. The classifier itself is
the AI observability ONNX model; it runs on the AEO Temporal queue, and this
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


@frozen
class BrandSentence:
    """One sentence of an answer that names the brand. `start` and `end` are offsets into the answer
    text in Unicode code points, and cover the whole trimmed sentence even when `text` is cut short."""

    start: int
    end: int
    text: str


@frozen
class SentenceSentiment:
    start: int
    end: int
    label: str
    score: float


def brand_sentences(answer_text: str | None, target_domains: list[str]) -> list[BrandSentence]:
    """The sentences of an answer that name the brand, in order, trimmed and bounded."""
    pattern = brand_pattern(target_domains)
    if not answer_text or pattern is None:
        return []
    sentences: list[BrandSentence] = []
    position = 0
    breaks = [match.span() for match in _SENTENCE_BREAK.finditer(answer_text)]
    for break_start, break_end in [*breaks, (len(answer_text), len(answer_text))]:
        raw = answer_text[position:break_start]
        text = raw.strip()
        if text and pattern.search(text):
            start = position + len(raw) - len(raw.lstrip())
            sentences.append(BrandSentence(start=start, end=start + len(text), text=text[:MAX_SENTENCE_CHARS]))
            if len(sentences) == MAX_BRAND_SENTENCES:
                break
        position = break_end
    return sentences


def sentence_sentiment(sentence: BrandSentence, scores: Mapping[str, float]) -> SentenceSentiment:
    """The label of one sentence, picked with the same neutral margin as the answer's label."""
    label = select_sentiment_label(dict(scores))
    return SentenceSentiment(start=sentence.start, end=sentence.end, label=label, score=round(scores[label], 4))


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
