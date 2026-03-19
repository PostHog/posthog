from typing import Any

import pytest

import numpy as np
from parameterized import parameterized

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.ensemble import EnsembleDetector
from posthog.tasks.alerts.detectors.registry import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.statistical.mad import MADDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector


class TestDetectorRegistry:
    def test_get_zscore_detector(self) -> None:
        config = {"type": "zscore", "threshold": 0.9, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, ZScoreDetector)

    def test_get_threshold_detector(self) -> None:
        config = {"type": "threshold", "upper_bound": 100, "lower_bound": 0}
        detector = get_detector(config)
        assert isinstance(detector, ThresholdDetector)

    def test_unknown_detector_raises(self) -> None:
        config = {"type": "unknown"}
        with pytest.raises(ValueError, match="Unknown detector type"):
            get_detector(config)

    def test_missing_type_raises(self) -> None:
        config = {"threshold": 0.9}
        with pytest.raises(ValueError, match="must have a 'type' field"):
            get_detector(config)

    def test_get_mad_detector(self) -> None:
        config = {"type": "mad", "threshold": 0.9, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, MADDetector)

    def test_get_available_detectors(self) -> None:
        detectors = get_available_detectors()
        assert "zscore" in detectors
        assert "mad" in detectors
        assert "threshold" in detectors
        assert "ensemble" in detectors


class TestAnomalyDetectors:
    @parameterized.expand(
        [
            (
                "zscore_obvious_anomaly",
                ZScoreDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100]),
                True,
            ),
            (
                "zscore_normal_data",
                ZScoreDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10]),
                False,
            ),
            (
                "zscore_insufficient_data",
                ZScoreDetector({"threshold": 0.9, "window": 30}),
                np.array([10, 11, 10, 10]),
                False,
            ),
            (
                "mad_obvious_anomaly",
                MADDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100]),
                True,
            ),
            (
                "mad_normal_data",
                MADDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10]),
                False,
            ),
            (
                "mad_insufficient_data",
                MADDetector({"threshold": 0.9, "window": 30}),
                np.array([10, 11, 10, 10]),
                False,
            ),
            (
                "mad_robust_to_outliers_in_window",
                MADDetector({"threshold": 0.9, "window": 10}),
                np.array([10, 12, 100, 9, 11, 8, 13, 10, 11, 9, 10, 12]),
                False,
            ),
        ]
    )
    def test_detect(self, _name: str, detector: Any, data: Any, expected_anomaly: bool) -> None:
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_scores_are_normalized_probabilities(self) -> None:
        """Scores from all detectors should be in the [0, 1] range."""
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        for detector in [
            ZScoreDetector({"threshold": 0.9, "window": 10}),
            MADDetector({"threshold": 0.9, "window": 10}),
        ]:
            result = detector.detect(data)
            assert result.score is not None
            assert 0.0 <= result.score <= 1.0, f"{type(detector).__name__} score {result.score} not in [0, 1]"

    def test_anomaly_scores_are_high(self) -> None:
        """Obvious anomalies should have scores close to 1.0."""
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        for detector in [
            ZScoreDetector({"threshold": 0.5, "window": 10}),
            MADDetector({"threshold": 0.5, "window": 10}),
        ]:
            result = detector.detect(data)
            assert result.score is not None
            assert result.score > 0.9, (
                f"{type(detector).__name__} score {result.score} should be > 0.9 for obvious anomaly"
            )

    @parameterized.expand(
        [
            (
                "zscore_batch",
                ZScoreDetector({"threshold": 0.9, "window": 5}),
                np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50]),
                2,
            ),
            (
                "mad_batch",
                MADDetector({"threshold": 0.9, "window": 5}),
                np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50]),
                2,
            ),
        ]
    )
    def test_detect_batch(self, _name: str, detector: Any, data: Any, min_triggered: int) -> None:
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= min_triggered

    def test_zscore_detect_returns_metadata(self) -> None:
        detector = ZScoreDetector({"threshold": 0.9, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "mean" in result.metadata
        assert "std" in result.metadata
        assert "value" in result.metadata
        assert "raw_zscore" in result.metadata

    def test_mad_detect_returns_metadata(self) -> None:
        detector = MADDetector({"threshold": 0.9, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "median" in result.metadata
        assert "median_abs_deviation" in result.metadata
        assert "value" in result.metadata
        assert "raw_score" in result.metadata


class TestThresholdDetector:
    @parameterized.expand(
        [
            (
                "upper_breach",
                {"upper_bound": 50, "lower_bound": 0},
                np.array([10, 20, 30, 60]),
                True,
            ),
            (
                "lower_breach",
                {"upper_bound": 50, "lower_bound": 0},
                np.array([10, 20, 30, -10]),
                True,
            ),
            (
                "no_breach",
                {"upper_bound": 50, "lower_bound": 0},
                np.array([10, 20, 30, 40]),
                False,
            ),
            (
                "only_upper_bound_breach",
                {"upper_bound": 50},
                np.array([10, 20, -100, 60]),
                True,
            ),
            (
                "only_upper_bound_no_breach",
                {"upper_bound": 50},
                np.array([10, 20, -100, 40]),
                False,
            ),
        ]
    )
    def test_detect(self, _name: str, config: Any, data: Any, expected_anomaly: bool) -> None:
        detector = ThresholdDetector(config)
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_detect_batch_finds_all_breaches(self) -> None:
        detector = ThresholdDetector({"upper_bound": 50, "lower_bound": 0})
        data = np.array([10, 60, 20, -10, 30])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) == 2


class TestDetectionResult:
    def test_default_values(self) -> None:
        result = DetectionResult(is_anomaly=False)
        assert not result.is_anomaly
        assert result.score is None
        assert result.triggered_indices == []
        assert result.all_scores == []
        assert result.metadata == {}

    def test_custom_values(self) -> None:
        result = DetectionResult(
            is_anomaly=True,
            score=0.95,
            triggered_indices=[10, 20],
            all_scores=[0.1, 0.3, 0.95],
            metadata={"test": "value"},
        )
        assert result.is_anomaly
        assert result.score == 0.95
        assert result.triggered_indices == [10, 20]
        assert result.all_scores == [0.1, 0.3, 0.95]
        assert result.metadata == {"test": "value"}


class TestEnsembleDetector:
    # Data with obvious anomaly at the end
    ANOMALY_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
    # Data with no anomaly
    NORMAL_DATA = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])

    @parameterized.expand(
        [
            (
                "and_both_flag",
                "and",
                ANOMALY_DATA,
                True,
            ),
            (
                "and_normal_data",
                "and",
                NORMAL_DATA,
                False,
            ),
            (
                "or_both_flag",
                "or",
                ANOMALY_DATA,
                True,
            ),
            (
                "or_normal_data",
                "or",
                NORMAL_DATA,
                False,
            ),
        ]
    )
    def test_detect(self, _name: str, operator: str, data: Any, expected_anomaly: bool) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": operator,
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_and_requires_all_detectors_to_agree(self) -> None:
        # Mild anomaly: zscore with low threshold flags, mad with high threshold doesn't
        mild_anomaly = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 15])
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.5, "window": 10},
                    {"type": "mad", "threshold": 0.99, "window": 10},
                ],
            }
        )
        result = detector.detect(mild_anomaly)
        # ZScore flags mild anomaly at low threshold, MAD at high threshold may not
        # AND requires both, so check sub-results diverge
        sub = result.metadata["sub_results"]
        if sub[0]["is_anomaly"] != sub[1]["is_anomaly"]:
            assert not result.is_anomaly

    def test_or_flags_if_any_detector_flags(self) -> None:
        mild_anomaly = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 15])
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.5, "window": 10},
                    {"type": "mad", "threshold": 0.99, "window": 10},
                ],
            }
        )
        result = detector.detect(mild_anomaly)
        sub = result.metadata["sub_results"]
        # OR should flag if at least one detector flags
        if any(s["is_anomaly"] for s in sub):
            assert result.is_anomaly

    def test_metadata_contains_sub_results(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(self.ANOMALY_DATA)
        assert "sub_results" in result.metadata
        assert len(result.metadata["sub_results"]) == 2
        assert result.metadata["sub_results"][0]["type"] == "zscore"
        assert result.metadata["sub_results"][1]["type"] == "mad"

    def test_score_is_min_for_and(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(self.ANOMALY_DATA)
        assert result.score is not None
        # AND uses min score
        sub_scores = [r["score"] for r in result.metadata["sub_results"]]
        assert result.score == min(s for s in sub_scores if s is not None)

    def test_score_is_max_for_or(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "or",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 10},
                    {"type": "mad", "threshold": 0.9, "window": 10},
                ],
            }
        )
        result = detector.detect(self.ANOMALY_DATA)
        assert result.score is not None
        # OR uses max score
        sub_scores = [r["score"] for r in result.metadata["sub_results"]]
        assert result.score == max(s for s in sub_scores if s is not None)

    def test_batch_and_intersects_triggered(self) -> None:
        detector = EnsembleDetector(
            {
                "type": "ensemble",
                "operator": "and",
                "detectors": [
                    {"type": "zscore", "threshold": 0.9, "window": 5},
                    {"type": "mad", "threshold": 0.9, "window": 5},
                ],
            }
        )
        data = np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        # AND should only include indices both detectors flagged
        assert len(result.triggered_indices) >= 1

    def test_registry_creates_ensemble(self) -> None:
        config = {
            "type": "ensemble",
            "operator": "or",
            "detectors": [
                {"type": "zscore", "threshold": 0.9, "window": 10},
                {"type": "mad", "threshold": 0.9, "window": 10},
            ],
        }
        detector = get_detector(config)
        assert isinstance(detector, EnsembleDetector)

    def test_fewer_than_two_detectors_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            EnsembleDetector(
                {
                    "type": "ensemble",
                    "operator": "and",
                    "detectors": [{"type": "zscore", "threshold": 0.9, "window": 10}],
                }
            )

    def test_invalid_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ensemble operator"):
            EnsembleDetector(
                {
                    "type": "ensemble",
                    "operator": "xor",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.9, "window": 10},
                        {"type": "mad", "threshold": 0.9, "window": 10},
                    ],
                }
            )
