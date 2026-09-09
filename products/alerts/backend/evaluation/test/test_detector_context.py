from typing import Any

from unittest.mock import MagicMock, patch

import numpy as np

from posthog.models.team import Team
from posthog.models.user import User
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectionContext, DetectionResult

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.alerts.backend.evaluation.detector import evaluate_with_detector

TRENDS_QUERY = {
    "kind": "InsightVizNode",
    "source": {
        "kind": "TrendsQuery",
        "interval": "day",
        "series": [{"kind": "EventsNode", "event": "signed_up", "math": "dau"}],
    },
}


class _RecordingDetector(BaseDetector):
    """Captures the context it is handed, and fires so the result shape is observable."""

    seen: list[DetectionContext] = []

    def detect(self, data: np.ndarray) -> DetectionResult:
        raise AssertionError("evaluate_with_detector must route through the context-aware entry point")

    def detect_batch(self, data: np.ndarray) -> DetectionResult:
        raise AssertionError("evaluate_with_detector must route through the context-aware entry point")

    def detect_in_context(self, data: np.ndarray, context: DetectionContext) -> DetectionResult:
        _RecordingDetector.seen.append(context)
        return DetectionResult(
            is_anomaly=True,
            score=0.88,
            triggered_indices=[len(data) - 1],
            all_scores=[0.88],
            metadata={"rationale": "Signups fell to 12.", "kind": "drop", "model": "claude-sonnet-5", "mean": 99.0},
        )


# The detector only reads identity off these, so a mock avoids a Postgres round trip for a
# test that scores an in-memory series.
FAKE_TEAM = MagicMock(spec=Team)
FAKE_USER = MagicMock(spec=User)


class _FakeInsight:
    name = "Daily signups"
    query = TRENDS_QUERY
    team = FAKE_TEAM


class _FakeAlert:
    config: dict[str, Any] = {"type": "TrendsAlertConfig", "series_index": 0}
    created_by = FAKE_USER


def _extraction() -> ExtractionResult:
    points = [SeriesPoint(date=f"2026-01-0{i + 1}", value=float(v)) for i, v in enumerate([100, 98, 101, 99, 12])]
    return ExtractionResult(
        series=[ComparableSeries(label="signed_up", points=points, current_index=len(points) - 1)],
        interval_type=None,
    )


def _evaluate(detector_config: dict[str, Any]) -> Any:
    _RecordingDetector.seen = []
    with patch(
        "products.alerts.backend.evaluation.detector.get_detector",
        return_value=_RecordingDetector(detector_config),
    ):
        return evaluate_with_detector(
            _extraction(),
            detector_config,
            insight=_FakeInsight(),  # type: ignore[arg-type]
            alert=_FakeAlert(),  # type: ignore[arg-type]
        )


class TestDetectionContextPlumbing:
    def test_detector_receives_the_series_calendar_and_metric_meaning(self) -> None:
        _evaluate({"type": "llm", "instructions": "Only care about drops"})

        context = _RecordingDetector.seen[0]
        assert context.dates == ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05")
        assert context.series_label == "signed_up"
        assert context.insight_name == "Daily signups"
        assert context.instructions == "Only care about drops"
        assert "signed_up" in context.metric_description
        assert context.team is FAKE_TEAM
        assert context.user is FAKE_USER

    def test_context_is_built_for_statistical_detectors_too(self) -> None:
        # One code path for every type: a detector added later reads the context without
        # anything in the evaluation layer having to opt it in.
        _evaluate({"type": "zscore", "threshold": 0.95})

        assert _RecordingDetector.seen[0].dates


class TestLLMVerdictReachesTheCheck:
    def test_rationale_is_in_the_breach_message_and_the_check_metadata(self) -> None:
        result = _evaluate({"type": "llm", "threshold": 0.7})

        assert result.breaches is not None
        assert "Signups fell to 12." in result.breaches[0]
        assert "using AI detector" in result.breaches[0]
        # The model's number is its own stated confidence, so the message must not call it a probability.
        assert "model confidence:" in result.breaches[0]
        assert "probability" not in result.breaches[0]
        assert result.triggered_metadata == {"rationale": "Signups fell to 12.", "kind": "drop"}

    def test_statistical_detector_metadata_stays_off_the_check(self) -> None:
        # The statistical detectors' metadata is fit state (means, thresholds); persisting it
        # would put internals in front of a person and into the firing event.
        result = _evaluate({"type": "zscore", "threshold": 0.95})

        assert result.triggered_metadata is None
        assert "Signups fell to 12." not in (result.breaches or [""])[0]
