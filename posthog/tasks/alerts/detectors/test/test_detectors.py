import pytest

import numpy as np

from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.registry import get_detector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector


class TestDetectorRegistry:
    def test_get_zscore_detector(self):
        config = {"type": "zscore", "threshold": 3.0, "window": 30}
        detector = get_detector(config)
        assert isinstance(detector, ZScoreDetector)

    def test_unknown_detector_raises(self):
        config = {"type": "unknown"}
        with pytest.raises(ValueError, match="Unknown detector type"):
            get_detector(config)

    def test_missing_type_raises(self):
        config = {"threshold": 3.0}
        with pytest.raises(ValueError, match="must have a 'type' field"):
            get_detector(config)


class TestZScoreDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 10})
        # Normal data followed by an extreme outlier
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly
        assert result.score is not None
        assert result.score > 3.0

    def test_detect_no_anomaly_in_normal_data(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 10})
        # All normal data
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_insufficient_data_returns_no_anomaly(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 30})
        # Not enough data for the window
        data = np.array([10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_batch_finds_multiple_anomalies(self):
        detector = ZScoreDetector({"threshold": 3.0, "window": 5})
        # Data with two outliers
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


class TestDetectionResult:
    def test_default_values(self):
        result = DetectionResult(is_anomaly=False)
        assert not result.is_anomaly
        assert result.score is None
        assert result.triggered_indices == []
        assert result.all_scores is None
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
