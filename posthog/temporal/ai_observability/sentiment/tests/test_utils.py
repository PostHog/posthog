from parameterized import parameterized

from posthog.temporal.ai_observability.sentiment.schema import PendingClassification, SentimentResult
from posthog.temporal.ai_observability.sentiment.utils import build_generation_result, select_sentiment_label


class TestSelectSentimentLabel:
    @parameterized.expand(
        [
            # Near-tie between a polar label and neutral resolves to neutral (the terse-query case).
            ("coin_flip_negative", {"negative": 0.504, "neutral": 0.468, "positive": 0.028}, "neutral"),
            ("coin_flip_positive", {"negative": 0.02, "neutral": 0.49, "positive": 0.49}, "neutral"),
            # Confident polar labels are kept.
            ("clear_negative", {"negative": 0.8, "neutral": 0.15, "positive": 0.05}, "negative"),
            ("clear_positive", {"negative": 0.05, "neutral": 0.15, "positive": 0.8}, "positive"),
            # Neutral winner is always neutral.
            ("neutral_winner", {"negative": 0.2, "neutral": 0.7, "positive": 0.1}, "neutral"),
            # Exactly at the margin is not enough to promote (strict beat required).
            ("exactly_at_margin", {"negative": 0.5, "neutral": 0.4, "positive": 0.1}, "neutral"),
        ]
    )
    def test_select_sentiment_label(self, _name: str, scores: dict[str, float], expected: str):
        assert select_sentiment_label(scores) == expected


class TestBuildGenerationResult:
    def test_stores_classified_text_and_applies_neutral_margin(self):
        pending = [
            PendingClassification(trace_id="t", gen_uuid="g", msg_index=17, text="retention graph for these people")
        ]
        # Coin-flip scores that argmax to negative but should resolve to neutral.
        classification = [
            SentimentResult(
                label="neutral", score=0.468, scores={"negative": 0.504, "neutral": 0.468, "positive": 0.028}
            )
        ]

        result = build_generation_result("g", pending, classification)

        assert result["label"] == "neutral"
        # The exact text that was classified is preserved for auditing, keyed by original message index.
        assert result["messages"]["17"]["text"] == "retention graph for these people"
