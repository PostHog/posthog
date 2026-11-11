import pytest

from products.aeo.backend.brand import brand_names, brand_regex
from products.aeo.backend.sentiment import (
    MAX_BRAND_SENTENCES,
    MAX_SENTENCE_CHARS,
    AnswerSentiment,
    aggregate_sentiment,
    brand_sentences,
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
        ("A counterexample: nothing here. Examples abound.", []),
        ("", []),
        (None, []),
    ],
)
def test_brand_sentences_keep_only_sentences_that_name_the_brand(answer: str | None, expected: list[str]):
    assert brand_sentences(answer, TARGET) == expected


def test_brand_sentences_are_bounded():
    answer = " ".join(f"Example point {index}." for index in range(MAX_BRAND_SENTENCES + 5)) + " Example " + "x" * 2000
    sentences = brand_sentences(answer, TARGET)
    assert len(sentences) == MAX_BRAND_SENTENCES
    assert all(len(sentence) <= MAX_SENTENCE_CHARS for sentence in sentences)
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
