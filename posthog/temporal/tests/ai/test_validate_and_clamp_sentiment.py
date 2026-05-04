import pytest

from parameterized import parameterized

from posthog.temporal.session_replay.session_summary.activities.video_based.a5_consolidate_video_segments import (
    _validate_and_clamp_sentiment,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    SentimentSignal,
    SessionSentiment,
    VideoSegmentOutcome,
    VideoSessionOutcome,
)

_SENTINEL = object()


def _make_segment(
    *,
    success: bool = True,
    confusion_detected: bool = False,
    abandonment_detected: bool = False,
    exception: str | None = None,
) -> ConsolidatedVideoSegment:
    return ConsolidatedVideoSegment(
        title="Test segment",
        start_time="0:00",
        end_time="1:00",
        description="Test",
        success=success,
        confusion_detected=confusion_detected,
        abandonment_detected=abandonment_detected,
        exception=exception,
    )


def _make_analysis(
    *,
    segments: list[ConsolidatedVideoSegment] | None = None,
    frustration_score: float = 0.5,
    outcome: str = "friction",
    sentiment_signals: list[SentimentSignal] | None = None,
    sentiment: SessionSentiment | None | object = _SENTINEL,
) -> ConsolidatedVideoAnalysis:
    if segments is None:
        segments = [_make_segment()]

    resolved_sentiment: SessionSentiment | None
    if sentiment is _SENTINEL:
        resolved_sentiment = SessionSentiment(
            frustration_score=frustration_score,
            outcome=outcome,
            sentiment_signals=sentiment_signals or [],
        )
    else:
        resolved_sentiment = sentiment  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    return ConsolidatedVideoAnalysis(
        segments=segments,
        session_outcome=VideoSessionOutcome(success=True, description="Test"),
        segment_outcomes=[
            VideoSegmentOutcome(segment_index=i, success=s.success, summary="Test") for i, s in enumerate(segments)
        ],
        sentiment=resolved_sentiment,
    )


class TestValidateAndClampSentiment:
    def test_returns_unchanged_when_no_sentiment(self):
        analysis = _make_analysis(sentiment=None)
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is None

    @parameterized.expand(
        [
            ("successful_passes_through_high", "successful", 0.9, 0.9),
            ("successful_passes_through_low", "successful", 0.1, 0.1),
            ("friction_floors_at_0_2", "friction", 0.05, 0.2),
            ("friction_keeps_high", "friction", 0.4, 0.4),
            ("frustrated_floors_at_0_5", "frustrated", 0.1, 0.5),
            ("frustrated_keeps_high", "frustrated", 0.8, 0.8),
            ("blocked_floors_at_0_75", "blocked", 0.1, 0.75),
            ("blocked_keeps_high", "blocked", 0.95, 0.95),
        ]
    )
    def test_outcome_clamps_score(self, _name, outcome, input_score, expected):
        analysis = _make_analysis(frustration_score=input_score, outcome=outcome)
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert result.sentiment.frustration_score == pytest.approx(expected, abs=0.01)
        assert result.sentiment.outcome == outcome

    def test_drops_signals_with_invalid_segment_index(self):
        signals = [
            SentimentSignal(signal_type="rage_click", segment_index=0, description="Valid", intensity=0.8),
            SentimentSignal(signal_type="dead_click", segment_index=5, description="Invalid", intensity=0.5),
            SentimentSignal(signal_type="backtracking", segment_index=99, description="Way out", intensity=0.3),
        ]
        analysis = _make_analysis(
            segments=[_make_segment()], sentiment_signals=signals, outcome="friction", frustration_score=0.3
        )
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert len(result.sentiment.sentiment_signals) == 1
        assert result.sentiment.sentiment_signals[0].signal_type == "rage_click"

    def test_keeps_all_valid_signals(self):
        signals = [
            SentimentSignal(signal_type="rage_click", segment_index=0, description="First", intensity=0.8),
            SentimentSignal(signal_type="dead_click", segment_index=1, description="Second", intensity=0.5),
        ]
        analysis = _make_analysis(
            segments=[_make_segment(), _make_segment()],
            sentiment_signals=signals,
            outcome="frustrated",
            frustration_score=0.6,
        )
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert len(result.sentiment.sentiment_signals) == 2

    def test_confusion_detected_raises_floor(self):
        analysis = _make_analysis(
            segments=[_make_segment(confusion_detected=True)],
            frustration_score=0.0,
            outcome="successful",
        )
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert result.sentiment.frustration_score >= 0.5

    def test_blocking_exception_raises_floor(self):
        analysis = _make_analysis(
            segments=[_make_segment(exception="blocking")],
            frustration_score=0.0,
            outcome="successful",
        )
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert result.sentiment.frustration_score >= 0.5

    def test_multiple_segments_dilute_signal_floor(self):
        segments = [_make_segment(confusion_detected=True), _make_segment(), _make_segment(), _make_segment()]
        analysis = _make_analysis(segments=segments, frustration_score=0.0, outcome="successful")
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert result.sentiment.frustration_score == pytest.approx(0.125, abs=0.01)

    def test_combined_confusion_and_blocking(self):
        segments = [_make_segment(confusion_detected=True, exception="blocking"), _make_segment()]
        analysis = _make_analysis(segments=segments, frustration_score=0.1, outcome="friction")
        result = _validate_and_clamp_sentiment(analysis)
        assert result.sentiment is not None
        assert result.sentiment.frustration_score >= 0.5

    def test_score_always_in_valid_range(self):
        for outcome in ["successful", "friction", "frustrated", "blocked"]:
            analysis = _make_analysis(frustration_score=1.0, outcome=outcome)
            result = _validate_and_clamp_sentiment(analysis)
            assert result.sentiment is not None
            assert 0.0 <= result.sentiment.frustration_score <= 1.0
