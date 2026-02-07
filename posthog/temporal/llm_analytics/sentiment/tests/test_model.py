"""Tests for sentiment model wrapper."""

from unittest.mock import patch

from posthog.temporal.llm_analytics.sentiment.model import SentimentResult, classify


class TestClassify:
    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_positive_classification(self, mock_load):
        mock_pipeline = lambda text: [
            [  # noqa: E731
                {"label": "positive", "score": 0.87},
                {"label": "neutral", "score": 0.10},
                {"label": "negative", "score": 0.03},
            ]
        ]
        mock_load.return_value = mock_pipeline

        result = classify("I love this product!")
        assert isinstance(result, SentimentResult)
        assert result.label == "positive"
        assert result.score == 0.87
        assert result.scores["positive"] == 0.87
        assert result.scores["neutral"] == 0.10
        assert result.scores["negative"] == 0.03

    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_negative_classification(self, mock_load):
        mock_pipeline = lambda text: [
            [  # noqa: E731
                {"label": "negative", "score": 0.92},
                {"label": "neutral", "score": 0.05},
                {"label": "positive", "score": 0.03},
            ]
        ]
        mock_load.return_value = mock_pipeline

        result = classify("This is terrible")
        assert result.label == "negative"
        assert result.score == 0.92

    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_neutral_classification(self, mock_load):
        mock_pipeline = lambda text: [
            [  # noqa: E731
                {"label": "neutral", "score": 0.75},
                {"label": "positive", "score": 0.15},
                {"label": "negative", "score": 0.10},
            ]
        ]
        mock_load.return_value = mock_pipeline

        result = classify("The weather is cloudy")
        assert result.label == "neutral"
        assert result.score == 0.75

    @patch("posthog.temporal.llm_analytics.sentiment.model._load_pipeline")
    def test_scores_rounded(self, mock_load):
        mock_pipeline = lambda text: [
            [  # noqa: E731
                {"label": "positive", "score": 0.87654321},
                {"label": "neutral", "score": 0.10123456},
                {"label": "negative", "score": 0.02222222},
            ]
        ]
        mock_load.return_value = mock_pipeline

        result = classify("test")
        assert result.scores["positive"] == 0.8765
        assert result.scores["neutral"] == 0.1012
        assert result.scores["negative"] == 0.0222
