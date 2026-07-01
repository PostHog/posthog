from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql_queries.ai.sentiment_evaluations import load_trace_sentiment_evaluations, normalize_sentiment_result
from posthog.models import Team

GenerationResultRow = tuple[object, object, object, object, object, object]


def _load_trace_sentiment_from_generation_results(generation_results: list[GenerationResultRow]) -> dict[str, object]:
    result = SimpleNamespace(results=[["trace-1", generation_results]])

    with patch("posthog.hogql_queries.ai.sentiment_evaluations.query_ai_events", return_value=result):
        sentiment_by_trace_id = load_trace_sentiment_evaluations(
            team=cast(Team, SimpleNamespace(id=1)),
            trace_ids=["trace-1"],
        )

    return cast(dict[str, object], sentiment_by_trace_id["trace-1"])


def test_load_trace_sentiment_evaluations_aggregates_generation_tuples() -> None:
    sentiment = _load_trace_sentiment_from_generation_results(
        [
            (
                "generation-1",
                "positive",
                0.9,
                {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
                {
                    "0": {
                        "label": "positive",
                        "score": 0.9,
                        "scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
                    }
                },
                1,
            )
        ]
    )

    assert sentiment["label"] == "positive"
    assert sentiment["score"] == 0.9
    assert sentiment["message_count"] == 1
    assert cast(dict[str, object], sentiment["messages"])["generation-1:0"] == {
        "label": "positive",
        "score": 0.9,
        "scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
    }


@parameterized.expand(
    [
        (
            "falls_back_to_generation_scores_when_message_scores_are_empty",
            [
                (
                    "generation-1",
                    "negative",
                    0.82,
                    {"positive": 0.02, "neutral": 0.16, "negative": 0.82},
                    {"0": {"label": "neutral"}},
                    1,
                )
            ],
            "negative",
            0.82,
        ),
        (
            "uses_message_scores_when_present",
            [
                (
                    "generation-1",
                    "negative",
                    0.82,
                    {"positive": 0.02, "neutral": 0.16, "negative": 0.82},
                    {
                        "0": {
                            "label": "positive",
                            "score": 0.91,
                            "scores": {"positive": 0.91, "neutral": 0.08, "negative": 0.01},
                        }
                    },
                    1,
                )
            ],
            "positive",
            0.91,
        ),
        (
            "uses_neutral_when_no_score_signal_exists",
            [
                (
                    "generation-1",
                    "positive",
                    None,
                    {},
                    {"0": {"label": "positive"}},
                    1,
                )
            ],
            "neutral",
            0.0,
        ),
    ]
)
def test_load_trace_sentiment_evaluations_handles_sparse_scores(
    _name: str,
    generation_results: list[GenerationResultRow],
    expected_label: str,
    expected_score: float,
) -> None:
    sentiment = _load_trace_sentiment_from_generation_results(generation_results)

    assert sentiment["label"] == expected_label
    assert sentiment["score"] == expected_score


@parameterized.expand(
    [
        ("string_values", "positive", "0.75", '{"positive":0.75,"neutral":0.2,"negative":0.05}', "2", 0.75, 2),
        ("invalid_label", "mixed", None, {}, None, 0.0, 0),
    ]
)
def test_normalize_sentiment_result_coerces_values(
    _name: str,
    label: object,
    score: object,
    scores: object,
    message_count: object,
    expected_score: float,
    expected_message_count: int,
) -> None:
    sentiment = normalize_sentiment_result(label, score, scores, {}, message_count)

    assert sentiment["score"] == expected_score
    assert sentiment["message_count"] == expected_message_count
