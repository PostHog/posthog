import pytest

import numpy as np
from parameterized import parameterized

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.registry import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.statistical.iqr import IQRDetector
from posthog.tasks.alerts.detectors.statistical.mad import MADDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector


class TestDetectorRegistry:
    def test_get_zscore_detector(self):
        config = {"type": "zscore", "threshold": 0.9, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, ZScoreDetector)

    def test_get_threshold_detector(self):
        config = {"type": "threshold", "upper_bound": 100, "lower_bound": 0}
        detector = get_detector(config)
        assert isinstance(detector, ThresholdDetector)

    def test_unknown_detector_raises(self):
        config = {"type": "unknown"}
        with pytest.raises(ValueError, match="Unknown detector type"):
            get_detector(config)

    def test_missing_type_raises(self):
        config = {"threshold": 0.9}
        with pytest.raises(ValueError, match="must have a 'type' field"):
            get_detector(config)

    def test_get_mad_detector(self):
        config = {"type": "mad", "threshold": 0.9, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, MADDetector)

    def test_get_iqr_detector(self):
        config = {"type": "iqr", "multiplier": 1.5, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, IQRDetector)

    def test_get_available_detectors(self):
        detectors = get_available_detectors()
        assert "zscore" in detectors
        assert "mad" in detectors
        assert "iqr" in detectors
        assert "threshold" in detectors


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
    def test_detect(self, _name, detector, data, expected_anomaly):
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_scores_are_normalized_probabilities(self):
        """Scores from all detectors should be in the [0, 1] range."""
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        for detector in [
            ZScoreDetector({"threshold": 0.9, "window": 10}),
            MADDetector({"threshold": 0.9, "window": 10}),
            IQRDetector({"threshold": 0.9, "window": 10}),
        ]:
            result = detector.detect(data)
            assert result.score is not None
            assert 0.0 <= result.score <= 1.0, f"{type(detector).__name__} score {result.score} not in [0, 1]"

    def test_anomaly_scores_are_high(self):
        """Obvious anomalies should have scores close to 1.0."""
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        for detector in [
            ZScoreDetector({"threshold": 0.5, "window": 10}),
            MADDetector({"threshold": 0.5, "window": 10}),
            IQRDetector({"threshold": 0.5, "window": 10}),
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
    def test_detect_batch(self, _name, detector, data, min_triggered):
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= min_triggered

    def test_zscore_detect_returns_metadata(self):
        detector = ZScoreDetector({"threshold": 0.9, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "mean" in result.metadata
        assert "std" in result.metadata
        assert "value" in result.metadata
        assert "raw_zscore" in result.metadata

    def test_mad_detect_returns_metadata(self):
        detector = MADDetector({"threshold": 0.9, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "median" in result.metadata
        assert "median_abs_deviation" in result.metadata
        assert "value" in result.metadata
        assert "raw_score" in result.metadata


class TestIQRDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_no_anomaly_in_normal_data(self):
        detector = IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_returns_metadata(self):
        detector = IQRDetector({"threshold": 0.9, "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "q1" in result.metadata
        assert "q3" in result.metadata
        assert "iqr" in result.metadata
        assert "raw_distance" in result.metadata


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
    def test_detect(self, _name, config, data, expected_anomaly):
        detector = ThresholdDetector(config)
        result = detector.detect(data)
        assert result.is_anomaly == expected_anomaly

    def test_detect_batch_finds_all_breaches(self):
        detector = ThresholdDetector({"upper_bound": 50, "lower_bound": 0})
        data = np.array([10, 60, 20, -10, 30])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) == 2


class TestDetectionResult:
    def test_default_values(self):
        result = DetectionResult(is_anomaly=False)
        assert not result.is_anomaly
        assert result.score is None
        assert result.triggered_indices == []
        assert result.all_scores == []
        assert result.metadata == {}

    def test_custom_values(self):
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
