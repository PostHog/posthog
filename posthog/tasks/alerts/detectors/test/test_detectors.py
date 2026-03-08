import pytest

import numpy as np

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.registry import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.statistical.mad import MADDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector
from posthog.tasks.alerts.detectors.threshold import ThresholdDetector


class TestDetectorRegistry:
    def test_get_zscore_detector(self):
        config = {"type": "zscore", "threshold": 3.0, "window": 30}
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
        config = {"threshold": 3.0}
        with pytest.raises(ValueError, match="must have a 'type' field"):
            get_detector(config)

    def test_get_mad_detector(self):
        config = {"type": "mad", "threshold": 3.5, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, MADDetector)

    def test_get_available_detectors(self):
        detectors = get_available_detectors()
        assert "zscore" in detectors
        assert "mad" in detectors
        assert "threshold" in detectors


class TestZScoreDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly
        assert result.score is not None
        assert result.score > 3.0

    def test_detect_no_anomaly_in_normal_data(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_insufficient_data_returns_no_anomaly(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 30})
        data = np.array([10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_batch_finds_multiple_anomalies(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 5})
        data = np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= 2

    def test_detect_returns_metadata(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "mean" in result.metadata
        assert "std" in result.metadata
        assert "value" in result.metadata


class TestMADDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = MADDetector({"threshold": 3.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly
        assert result.score is not None
        assert result.score > 3.5

    def test_detect_no_anomaly_in_normal_data(self):
        detector = MADDetector({"threshold": 3.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_insufficient_data_returns_no_anomaly(self):
        detector = MADDetector({"threshold": 3.5, "window": 30})
        data = np.array([10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_batch_finds_multiple_anomalies(self):
        detector = MADDetector({"threshold": 3.5, "window": 5})
        data = np.array([10, 10, 10, 10, 10, 10, 100, 10, 10, 10, 10, 10, -50])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) >= 2

    def test_detect_returns_metadata(self):
        detector = MADDetector({"threshold": 3.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert "median" in result.metadata
        assert "median_abs_deviation" in result.metadata
        assert "value" in result.metadata

    def test_robust_to_outliers_in_window(self):
        detector = MADDetector({"threshold": 3.5, "window": 10})
        # Window has an outlier (100) but MAD baseline stays stable due to median
        data = np.array([10, 12, 100, 9, 11, 8, 13, 10, 11, 9, 10, 12])
        result = detector.detect(data)
        # 12 is close to median (~10), should not be flagged even with outlier in window
        assert not result.is_anomaly


class TestThresholdDetector:
    def test_detect_upper_breach(self):
        detector = ThresholdDetector({"upper_bound": 50, "lower_bound": 0})
        data = np.array([10, 20, 30, 60])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_lower_breach(self):
        detector = ThresholdDetector({"upper_bound": 50, "lower_bound": 0})
        data = np.array([10, 20, 30, -10])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_no_breach(self):
        detector = ThresholdDetector({"upper_bound": 50, "lower_bound": 0})
        data = np.array([10, 20, 30, 40])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_with_only_upper_bound(self):
        detector = ThresholdDetector({"upper_bound": 50})
        data = np.array([10, 20, -100, 60])
        result = detector.detect(data)
        assert result.is_anomaly

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
            score=5.0,
            triggered_indices=[10, 20],
            all_scores=[1.0, 2.0, 5.0],
            metadata={"test": "value"},
        )
        assert result.is_anomaly
        assert result.score == 5.0
        assert result.triggered_indices == [10, 20]
        assert result.all_scores == [1.0, 2.0, 5.0]
        assert result.metadata == {"test": "value"}
