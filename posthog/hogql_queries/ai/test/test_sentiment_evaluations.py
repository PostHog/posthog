from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from posthog.hogql_queries.ai.sentiment_evaluations import load_trace_sentiment_evaluations
from posthog.models import Team


def test_load_trace_sentiment_evaluations_aggregates_generation_tuples() -> None:
    result = SimpleNamespace(
        results=[
            [
                "trace-1",
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
                ],
            ]
        ]
    )

    with patch("posthog.hogql_queries.ai.sentiment_evaluations.query_ai_events", return_value=result):
        sentiment_by_trace_id = load_trace_sentiment_evaluations(
            team=cast(Team, SimpleNamespace(id=1)),
            trace_ids=["trace-1"],
        )

    assert sentiment_by_trace_id["trace-1"]["label"] == "positive"
    assert sentiment_by_trace_id["trace-1"]["score"] == 0.9
    assert sentiment_by_trace_id["trace-1"]["message_count"] == 1
    assert sentiment_by_trace_id["trace-1"]["messages"]["generation-1:0"]["label"] == "positive"
