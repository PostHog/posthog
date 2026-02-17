from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.sentiment.model import SentimentResult, classify, classify_batch


def _make_pipeline_output(label: str, score: float) -> list[dict[str, object]]:
    """Build a single pipeline result (list of label/score dicts)."""
    labels_scores = {
        "positive": 0.05,
        "neutral": 0.05,
        "negative": 0.05,
    }
    labels_scores[label] = score
    return [{"label": name, "score": s} for name, s in labels_scores.items()]


class TestClassifyBatch:
    @parameterized.expand(
        [
            ("empty_input", [], []),
            (
                "single_text",
                ["hello"],
                [
                    SentimentResult(
                        label="positive", score=0.9, scores={"positive": 0.9, "neutral": 0.05, "negative": 0.05}
                    )
                ],
            ),
            (
                "multiple_texts",
                ["great", "terrible"],
                [
                    SentimentResult(
                        label="positive", score=0.9, scores={"positive": 0.9, "neutral": 0.05, "negative": 0.05}
                    ),
                    SentimentResult(
                        label="negative", score=0.8, scores={"positive": 0.05, "neutral": 0.05, "negative": 0.8}
                    ),
                ],
            ),
        ]
    )
    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_classify_batch(self, _name: str, texts: list[str], expected: list[SentimentResult], mock_load: MagicMock):
        if not texts:
            result = classify_batch(texts)
            assert result == expected
            mock_load.assert_not_called()
            return

        mock_pipe = MagicMock()
        labels = ["positive", "negative", "neutral", "positive"]
        pipeline_outputs = []
        for i, _text in enumerate(texts):
            label = labels[i % len(labels)]
            score = 0.9 if label == "positive" else 0.8
            pipeline_outputs.append(_make_pipeline_output(label, score))

        mock_pipe.return_value = pipeline_outputs
        mock_load.return_value = mock_pipe

        result = classify_batch(texts)

        mock_pipe.assert_called_once_with(texts, batch_size=32)
        assert len(result) == len(expected)
        for r, e in zip(result, expected):
            assert r.label == e.label
            assert r.score == e.score

    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_classify_delegates_to_batch(self, mock_load: MagicMock):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [_make_pipeline_output("neutral", 0.7)]
        mock_load.return_value = mock_pipe

        result = classify("test text")

        mock_pipe.assert_called_once_with(["test text"], batch_size=32)
        assert result.label == "neutral"
        assert result.score == 0.7

    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_missing_labels_filled_with_zero(self, mock_load: MagicMock):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [[{"label": "positive", "score": 0.95}]]
        mock_load.return_value = mock_pipe

        result = classify_batch(["text"])

        assert result[0].scores["neutral"] == 0.0
        assert result[0].scores["negative"] == 0.0
        assert result[0].scores["positive"] == 0.95
