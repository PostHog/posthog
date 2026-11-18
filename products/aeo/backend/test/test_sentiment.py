import pytest

from products.aeo.backend.brand import brand_names, brand_regex
from products.aeo.backend.sentiment import (
    MAX_BRAND_SENTENCES,
    MAX_SENTENCE_CHARS,
    AnswerSentiment,
    BrandSentence,
    SentenceSentiment,
    aggregate_sentiment,
    brand_sentences,
    sentence_sentiment,
)

TARGET = ["docs.example.co.uk", "Example.com"]


@pytest.mark.parametrize(
    "domains, names, regex",
    [
        (TARGET, ("example",), r"\m(example)\M"),
        (["posthog.com", "rival.io"], ("posthog", "rival"), r"\m(posthog|rival)\M"),
        ([], (), None),
        (["", "example.com"], ("example",), r"\m(example)\M"),
    ],
)
def test_brand_names_come_from_the_registrable_domain(domains: list[str], names: tuple[str, ...], regex: str | None):
    assert brand_names(domains) == names
    assert brand_regex(domains) == regex


@pytest.mark.parametrize(
    "answer, expected",
    [
        (
            "Example is fast. Rival is cheaper! Pick Example if you self-host?",
            ["Example is fast.", "Pick Example if you self-host?"],
        ),
        ("EXAMPLE works\nRival too\nexample's docs help", ["EXAMPLE works", "example's docs help"]),
        ("\U0001f680 Rival first\n  - Example is second.  \n", ["- Example is second."]),
        ("A counterexample: nothing here. Examples abound.", []),
        ("", []),
        (None, []),
    ],
)
def test_brand_sentences_keep_only_sentences_that_name_the_brand(answer: str | None, expected: list[str]):
    sentences = brand_sentences(answer, TARGET)
    assert [sentence.text for sentence in sentences] == expected
    assert [(answer or "")[sentence.start : sentence.end] for sentence in sentences] == expected


def test_brand_sentences_are_bounded():
    answer = " ".join(f"Example point {index}." for index in range(MAX_BRAND_SENTENCES + 5)) + " Example " + "x" * 2000
    sentences = brand_sentences(answer, TARGET)
    assert len(sentences) == MAX_BRAND_SENTENCES
    assert all(len(sentence.text) <= MAX_SENTENCE_CHARS for sentence in sentences)
    assert answer[sentences[-1].start : sentences[-1].end] == f"Example point {MAX_BRAND_SENTENCES - 1}."
    assert brand_sentences("Example is fine.", []) == []


@pytest.mark.parametrize(
    "scores, expected",
    [
        ([], None),
        ([{"positive": 0.9, "neutral": 0.08, "negative": 0.02}], AnswerSentiment(label="positive", score=0.9)),
        # The mean decides: one strongly negative sentence beats two mildly neutral ones.
        (
            [
                {"positive": 0.1, "neutral": 0.5, "negative": 0.4},
                {"positive": 0.05, "neutral": 0.45, "negative": 0.5},
                {"positive": 0.0, "neutral": 0.05, "negative": 0.95},
            ],
            AnswerSentiment(label="negative", score=0.6167),
        ),
        # A polar label that only just beats neutral stays neutral, as in AI observability.
        ([{"positive": 0.5, "neutral": 0.4, "negative": 0.1}], AnswerSentiment(label="neutral", score=0.4)),
        ([{"positive": 1.0}], AnswerSentiment(label="positive", score=1.0)),
    ],
)
def test_aggregate_sentiment_averages_sentence_scores_before_labeling(scores: list[dict[str, float]], expected):
    assert aggregate_sentiment(scores) == expected


@pytest.mark.parametrize(
    "scores, label, score",
    [
        ({"positive": 0.05, "neutral": 0.15, "negative": 0.8}, "negative", 0.8),
        # The same neutral margin as the answer's label, so a sentence is never more polar than its answer.
        ({"positive": 0.5, "neutral": 0.4, "negative": 0.1}, "neutral", 0.4),
    ],
)
def test_sentence_sentiment_keeps_the_span_and_labels_with_the_neutral_margin(
    scores: dict[str, float], label: str, score: float
):
    sentence = BrandSentence(start=4, end=20, text="Example is fine.")
    assert sentence_sentiment(sentence, scores) == SentenceSentiment(start=4, end=20, label=label, score=score)
