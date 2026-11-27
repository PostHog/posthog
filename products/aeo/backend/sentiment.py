"""How an answer engine's reply speaks about the brand.

Only the sentences that name the brand are scored, so praise of a competitor in
the same answer does not count as praise of the brand. The classifier itself is
the AI observability ONNX model; it runs on the AEO Temporal queue, and this
module only prepares its input and folds its output back into one label per answer.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.sentiment_labeling import select_sentiment_label

from products.aeo.backend.brand import brand_pattern

SENTIMENT_LABELS = ("negative", "neutral", "positive")
# Stored on a brand row whose mentions no sentence of the answer holds, so the backlog moves past it.
UNSCORABLE = "unscorable"
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
class MentionSpan:
    """Where a stored mention sits in the answer text, as offsets in Unicode code points."""

    start: int
    end: int


@frozen
class SentenceSentiment:
    start: int
    end: int
    label: str
    score: float


def brand_sentences(answer_text: str | None, target_domains: list[str]) -> list[BrandSentence]:
    """The sentences of an answer that name the brand, in order, trimmed and bounded."""
    return matching_sentences(answer_text, brand_pattern(target_domains))


def mention_sentences(answer_text: str | None, spans: Iterable[MentionSpan]) -> list[BrandSentence]:
    """The sentences of an answer that hold one of the mention spans, in order, trimmed and bounded.

    `spans` come from the offsets `AEOCheckBrand.mentions` stores. A break
    inside a mention, or right after punctuation that ends one, does not end the sentence, so `Dr. Martens is
    fast.` and `Yahoo! is fast.` each stay one sentence with their brand in it."""
    mentions = sorted(spans, key=lambda span: (span.start, span.end))
    if not answer_text or not mentions:
        return []

    def in_mention(position: int) -> bool:
        return any(span.start <= position < span.end for span in mentions)

    return _sentences(
        answer_text,
        wanted=lambda start, end: any(start < span.end and span.start < end for span in mentions),
        # The break's first character follows the punctuation that ends the sentence.
        breaks_at=lambda break_start, break_end: not in_mention(break_start - 1) and not in_mention(break_start),
    )


def matching_sentences(answer_text: str | None, pattern: re.Pattern[str] | None) -> list[BrandSentence]:
    """The sentences of an answer that the pattern matches, in order, trimmed and bounded."""
    if not answer_text or pattern is None:
        return []
    return _sentences(answer_text, wanted=lambda start, end: bool(pattern.search(answer_text, start, end)))


def _sentences(
    answer_text: str,
    *,
    wanted: Callable[[int, int], bool],
    breaks_at: Callable[[int, int], bool] = lambda break_start, break_end: True,
) -> list[BrandSentence]:
    sentences: list[BrandSentence] = []
    position = 0
    breaks = [match.span() for match in _SENTENCE_BREAK.finditer(answer_text) if breaks_at(*match.span())]
    for break_start, break_end in [*breaks, (len(answer_text), len(answer_text))]:
        raw = answer_text[position:break_start]
        text = raw.strip()
        start = position + len(raw) - len(raw.lstrip())
        if text and wanted(start, start + len(text)):
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
