import pytest

import numpy as np

from posthog.schema import DetectorType

from posthog.tasks.alerts.detectors import get_available_detectors, get_detector
from posthog.tasks.alerts.detectors.base import DetectionResult


class TestDetectorRegistry:
    def test_get_available_detectors_returns_all_types(self):
        detectors = get_available_detectors()
        expected = [
            DetectorType.THRESHOLD.value,
            DetectorType.ZSCORE.value,
            DetectorType.MAD.value,
            DetectorType.IQR.value,
            DetectorType.ISOLATION_FOREST.value,
            DetectorType.ECOD.value,
            DetectorType.COPOD.value,
            DetectorType.KNN.value,
            DetectorType.ENSEMBLE.value,
        ]
        for expected_type in expected:
            assert expected_type in detectors

    def test_get_detector_creates_correct_type(self):
        from posthog.tasks.alerts.detectors.threshold import ThresholdDetector

        detector = get_detector({"type": "threshold", "lower": 0, "upper": 100})
        assert isinstance(detector, ThresholdDetector)

    def test_get_detector_raises_for_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown detector type"):
            get_detector({"type": "nonexistent"})


class TestThresholdDetector:
    def test_detect_triggers_above_upper_threshold(self):
        detector = get_detector({"type": "threshold", "bounds": {"upper": 100}})
        data = np.array([50, 60, 70, 150])
        result = detector.detect(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) == 1
        assert result.triggered_indices[0] == 3

    def test_detect_triggers_below_lower_threshold(self):
        detector = get_detector({"type": "threshold", "bounds": {"lower": 10}})
        data = np.array([50, 60, 70, 5])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_no_anomaly_within_bounds(self):
        detector = get_detector({"type": "threshold", "bounds": {"lower": 0, "upper": 100}})
        data = np.array([50, 60, 70, 80])
        result = detector.detect(data)
        assert not result.is_anomaly
        assert result.triggered_indices == []

    def test_detect_batch_finds_all_anomalies(self):
        detector = get_detector({"type": "threshold", "bounds": {"lower": 10, "upper": 100}})
        data = np.array([50, 5, 70, 150, 30])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert 1 in result.triggered_indices
        assert 3 in result.triggered_indices


class TestZScoreDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "zscore", "threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly
        assert result.score is not None
        assert result.score > 3.0

    def test_detect_no_anomaly_in_normal_data(self):
        detector = get_detector({"type": "zscore", "threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_detect_batch_returns_scores_for_all_points(self):
        detector = get_detector({"type": "zscore", "threshold": 3.0, "window": 5})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 100])
        result = detector.detect_batch(data)
        assert result.all_scores is not None
        assert len(result.all_scores) == len(data)

    def test_insufficient_data_returns_no_anomaly(self):
        detector = get_detector({"type": "zscore", "threshold": 3.0, "window": 30})
        data = np.array([10, 11, 10, 9, 10])
        result = detector.detect(data)
        assert not result.is_anomaly


class TestMADDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "mad", "threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_no_anomaly_in_normal_data(self):
        detector = get_detector({"type": "mad", "threshold": 3.0, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly


class TestIQRDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "iqr", "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_no_anomaly_in_normal_data(self):
        detector = get_detector({"type": "iqr", "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 10])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_metadata_includes_fence_values(self):
        detector = get_detector({"type": "iqr", "multiplier": 1.5, "window": 10})
        data = np.array([10, 11, 10, 9, 10, 11, 10, 9, 10, 11, 10, 100])
        result = detector.detect(data)
        assert "lower_fence" in result.metadata
        assert "upper_fence" in result.metadata
        assert "iqr" in result.metadata


class TestIsolationForestDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "isolation_forest", "contamination": 0.1})
        np.random.seed(42)
        normal_data = np.random.normal(50, 5, 20)
        data = np.append(normal_data, [200])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_detect_batch_identifies_outliers(self):
        detector = get_detector({"type": "isolation_forest", "contamination": 0.1})
        np.random.seed(42)
        normal_data = np.random.normal(50, 5, 18)
        data = np.append(normal_data, [200, 200])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert len(result.triggered_indices) > 0

    def test_insufficient_data_returns_no_anomaly(self):
        detector = get_detector({"type": "isolation_forest", "contamination": 0.1})
        data = np.array([10, 11, 10, 9, 10])
        result = detector.detect(data)
        assert not result.is_anomaly


class TestECODDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "ecod", "contamination": 0.1})
        np.random.seed(42)
        normal_data = np.random.normal(50, 5, 20)
        data = np.append(normal_data, [200])
        result = detector.detect(data)
        assert result.is_anomaly


class TestCOPODDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "copod", "contamination": 0.1})
        np.random.seed(42)
        normal_data = np.random.normal(50, 5, 20)
        data = np.append(normal_data, [200])
        result = detector.detect(data)
        assert result.is_anomaly


class TestKNNDetector:
    def test_detect_finds_obvious_anomaly(self):
        detector = get_detector({"type": "knn", "contamination": 0.1, "n_neighbors": 3})
        np.random.seed(42)
        normal_data = np.random.normal(50, 5, 20)
        data = np.append(normal_data, [200])
        result = detector.detect(data)
        assert result.is_anomaly


class TestEnsembleDetector:
    def test_or_mode_triggers_if_any_detector_triggers(self):
        config = {
            "type": "ensemble",
            "mode": "or",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 200}},
                {"type": "threshold", "bounds": {"upper": 50}},
            ],
        }
        detector = get_detector(config)
        data = np.array([40, 45, 50, 75])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_and_mode_requires_all_detectors_to_trigger(self):
        config = {
            "type": "ensemble",
            "mode": "and",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 50}},
            ],
        }
        detector = get_detector(config)
        data = np.array([40, 45, 50, 75])
        result = detector.detect(data)
        assert not result.is_anomaly

    def test_and_mode_triggers_when_all_trigger(self):
        config = {
            "type": "ensemble",
            "mode": "and",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 50}},
                {"type": "threshold", "bounds": {"upper": 70}},
            ],
        }
        detector = get_detector(config)
        data = np.array([40, 45, 50, 150])
        result = detector.detect(data)
        assert result.is_anomaly

    def test_minimum_detectors_validation(self):
        config = {
            "type": "ensemble",
            "mode": "or",
            "detectors": [{"type": "threshold", "bounds": {"upper": 100}}],
        }
        with pytest.raises(ValueError, match="at least 2 detectors"):
            get_detector(config)

    def test_maximum_detectors_validation(self):
        config = {
            "type": "ensemble",
            "mode": "or",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"upper": 100}},
            ],
        }
        with pytest.raises(ValueError, match="at most 5 detectors"):
            get_detector(config)

    def test_no_nested_ensembles(self):
        config = {
            "type": "ensemble",
            "mode": "or",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 100}},
                {
                    "type": "ensemble",
                    "mode": "and",
                    "detectors": [
                        {"type": "threshold", "bounds": {"upper": 50}},
                        {"type": "threshold", "bounds": {"upper": 75}},
                    ],
                },
            ],
        }
        with pytest.raises(ValueError, match="[Nn]ested ensembles"):
            get_detector(config)

    def test_batch_detection_aggregates_results(self):
        config = {
            "type": "ensemble",
            "mode": "or",
            "detectors": [
                {"type": "threshold", "bounds": {"upper": 100}},
                {"type": "threshold", "bounds": {"lower": 10}},
            ],
        }
        detector = get_detector(config)
        data = np.array([50, 5, 70, 150, 30])
        result = detector.detect_batch(data)
        assert result.is_anomaly
        assert 1 in result.triggered_indices
        assert 3 in result.triggered_indices


class TestPreprocessing:
    def test_first_difference(self):
        from posthog.tasks.alerts.detectors.preprocessing import first_difference

        data = np.array([10, 15, 12, 20])
        result = first_difference(data)
        # Implementation uses prepend to maintain length
        expected = np.array([0, 5, -3, 8])
        np.testing.assert_array_equal(result, expected)

    def test_moving_average(self):
        from posthog.tasks.alerts.detectors.preprocessing import moving_average

        data = np.array([10, 20, 30, 40, 50])
        result = moving_average(data, window=3)
        # Implementation uses edge padding for convolution
        assert len(result) == len(data)
        # The middle values should be proper averages: (20+30+40)/3=30
        np.testing.assert_almost_equal(result[2], 30.0)

    def test_exponential_smoothing(self):
        from posthog.tasks.alerts.detectors.preprocessing import exponential_smoothing

        data = np.array([10, 20, 30, 40])
        result = exponential_smoothing(data, alpha=0.5)
        assert len(result) == len(data)
        assert result[0] == 10

    def test_create_lag_features(self):
        from posthog.tasks.alerts.detectors.preprocessing import create_lag_features

        data = np.array([1, 2, 3, 4, 5])
        result = create_lag_features(data, n_lags=2)
        # Implementation pads with first value to maintain length
        assert result.shape[1] == 3  # current + 2 lags
        assert result.shape[0] == 5  # All rows preserved
        # First column is original data
        np.testing.assert_array_equal(result[:, 0], data)

    def test_preprocess_data_with_smoothing(self):
        from posthog.tasks.alerts.detectors.preprocessing import preprocess_data

        data = np.array([10, 20, 30, 40, 50])
        config = {"smoothing": "moving_average", "smoothing_window": 3}
        result = preprocess_data(data, config)
        assert len(result) == len(data)

    def test_preprocess_data_with_diffs(self):
        from posthog.tasks.alerts.detectors.preprocessing import preprocess_data

        data = np.array([10, 20, 30, 40, 50])
        config = {"diffs": True}
        result = preprocess_data(data, config)
        # Implementation uses prepend to maintain length
        assert len(result) == len(data)

    def test_preprocess_preserves_data_when_no_config(self):
        from posthog.tasks.alerts.detectors.preprocessing import preprocess_data

        data = np.array([10, 20, 30, 40, 50])
        result = preprocess_data(data, None)
        np.testing.assert_array_equal(result, data)


class TestDetectionResult:
    def test_default_values(self):
        result = DetectionResult(is_anomaly=True)
        assert result.is_anomaly is True
        assert result.score is None
        assert result.triggered_indices == []
        assert result.all_scores == []
        assert result.metadata == {}

    def test_custom_values(self):
        result = DetectionResult(
            is_anomaly=True,
            score=3.5,
            triggered_indices=[1, 3, 5],
            all_scores=[1.0, 3.5, 2.0, 4.0, 1.5, 3.8],
            metadata={"key": "value"},
        )
        assert result.score == 3.5
        assert result.triggered_indices == [1, 3, 5]
        assert len(result.all_scores) == 6
        assert result.metadata["key"] == "value"
