from parameterized import parameterized

from posthog.temporal.ai_observability.sentiment.schema import PendingClassification, SentimentResult
from posthog.temporal.ai_observability.sentiment.utils import build_generation_result, resolve_label


class TestResolveLabel:
    @parameterized.expand(
        [
            ("confident_negative", {"negative": 0.8, "neutral": 0.1, "positive": 0.1}, "negative"),
            ("confident_positive", {"negative": 0.05, "neutral": 0.05, "positive": 0.9}, "positive"),
            ("neutral_top", {"negative": 0.2, "neutral": 0.6, "positive": 0.2}, "neutral"),
            # Terse product command: negative narrowly beats neutral -> calibrated to neutral.
            ("weak_negative_falls_back", {"negative": 0.45, "neutral": 0.40, "positive": 0.15}, "neutral"),
            ("weak_positive_falls_back", {"negative": 0.05, "neutral": 0.45, "positive": 0.50}, "neutral"),
            # Margin is inclusive: a gap of exactly 0.15 keeps the non-neutral label.
            ("at_margin_keeps_negative", {"negative": 0.55, "neutral": 0.40, "positive": 0.05}, "negative"),
            ("empty_scores", {}, "neutral"),
        ]
    )
    def test_resolve_label(self, _name: str, scores: dict[str, float], expected: str):
        assert resolve_label(scores) == expected


class TestBuildGenerationResult:
    def test_aggregate_label_passes_through_neutral_band(self):
        # Averaged scores where negative narrowly beats neutral. The generation-level
        # label must be calibrated to neutral, not the raw argmax (negative).
        pending = [PendingClassification(trace_id="t", gen_uuid="g", msg_index=0, text="do the thing")]
        scores = {"negative": 0.45, "neutral": 0.40, "positive": 0.15}
        results = [SentimentResult(label="neutral", score=0.40, scores=scores)]

        generation = build_generation_result("g", pending, results)

        assert generation["label"] == "neutral"
        assert generation["message_count"] == 1
