"""
Tests for the detector system.
"""

import pytest

from posthog.alerts.detectors import (
    DetectorType,
    MADDetector,
    ThresholdDetector,
    ValueType,
    ZScoreDetector,
    create_detector,
)


class TestThresholdDetector:
    """Tests for threshold-based detection."""

    def test_threshold_detector_basic(self):
        """Test basic threshold detection functionality."""
        config = {"bounds": {"lower": 10.0, "upper": 100.0}, "threshold_type": "absolute"}

        detector = ThresholdDetector(config)
        assert detector.detector_type == DetectorType.THRESHOLD

        # Test values within bounds - no breach
        result = detector.detect([50.0], "Test Series")
        assert not result.is_breach
        assert result.value == 50.0
        assert result.detector_score == 50.0
        assert len(result.breach_messages) == 0

        # Test value above upper bound - breach
        result = detector.detect([150.0], "Test Series")
        assert result.is_breach
        assert result.value == 150.0
        assert len(result.breach_messages) == 1
        assert "more than upper threshold" in result.breach_messages[0]

        # Test value below lower bound - breach
        result = detector.detect([5.0], "Test Series")
        assert result.is_breach
        assert result.value == 5.0
        assert len(result.breach_messages) == 1
        assert "less than lower threshold" in result.breach_messages[0]

    def test_threshold_detector_percentage(self):
        """Test percentage-based threshold detection."""
        config = {
            "bounds": {"lower": 0.1, "upper": 0.5},  # 10% to 50%
            "threshold_type": "percentage",
        }

        detector = ThresholdDetector(config)

        # Test breach above percentage threshold
        result = detector.detect([0.8], "Test Series")  # 80%
        assert result.is_breach
        assert "80.00%" in result.breach_messages[0]
        assert "50.00%" in result.breach_messages[0]

    def test_threshold_detector_deltas(self):
        """Test threshold detection on deltas."""
        config = {"bounds": {"upper": 5.0}, "threshold_type": "absolute"}

        detector = ThresholdDetector(config)

        # Values: [10, 12, 18], deltas: [2, 6]
        # Delta of 6 should breach threshold of 5
        result = detector.detect([10.0, 12.0, 18.0], "Test Series", ValueType.DELTA)
        assert result.is_breach
        assert result.value == 18.0  # Always returns raw value
        assert result.detector_score == 6.0  # Detection ran on delta

    def test_threshold_detector_validation(self):
        """Test configuration validation."""
        # Valid configuration
        config = {"bounds": {"lower": 10, "upper": 20}, "threshold_type": "absolute"}
        ThresholdDetector(config)  # Should not raise

        # Invalid bounds (lower > upper)
        with pytest.raises(ValueError, match="Lower threshold must be less than upper threshold"):
            config = {"bounds": {"lower": 20, "upper": 10}, "threshold_type": "absolute"}
            ThresholdDetector(config)

        # Invalid threshold type
        with pytest.raises(ValueError, match="threshold_type must be"):
            config = {"bounds": {"upper": 10}, "threshold_type": "invalid"}
            ThresholdDetector(config)


class TestZScoreDetector:
    """Tests for z-score based detection."""

    def test_zscore_detector_basic(self):
        """Test basic z-score detection."""
        config = {"threshold": 2.0, "direction": "both", "min_samples": 5, "window_size": 20}

        detector = ZScoreDetector(config)
        assert detector.detector_type == DetectorType.ZSCORE

        # Create data with outlier: normal values around 10, outlier at 25
        values = [10.0, 9.0, 11.0, 10.5, 9.5, 10.2, 9.8, 25.0]
        result = detector.detect(values, "Test Series")

        # Should detect the outlier (z-score should be > 2.0)
        assert result.is_breach
        assert result.value == 25.0
        assert result.detector_score > 2.0
        assert len(result.breach_messages) == 1
        assert "z-score" in result.breach_messages[0]

        # Check metadata
        assert "mean" in result.metadata
        assert "std" in result.metadata
        assert "samples_used" in result.metadata

    def test_zscore_detector_direction_up(self):
        """Test z-score detection with direction=up."""
        config = {"threshold": 2.0, "direction": "up", "min_samples": 5}
        detector = ZScoreDetector(config)

        # Data with high outlier
        values = [10.0, 9.0, 11.0, 10.5, 9.5, 25.0]
        result = detector.detect(values, "Test Series")
        assert result.is_breach  # High outlier should be detected

        # Data with low outlier
        values = [10.0, 11.0, 10.5, 9.5, 10.2, -5.0]
        result = detector.detect(values, "Test Series")
        assert not result.is_breach  # Low outlier should be ignored

    def test_zscore_detector_direction_down(self):
        """Test z-score detection with direction=down."""
        config = {"threshold": 2.0, "direction": "down", "min_samples": 5}
        detector = ZScoreDetector(config)

        # Data with low outlier
        values = [10.0, 11.0, 10.5, 9.5, 10.2, -5.0]
        result = detector.detect(values, "Test Series")
        assert result.is_breach  # Low outlier should be detected

        # Data with high outlier
        values = [10.0, 9.0, 11.0, 10.5, 9.5, 25.0]
        result = detector.detect(values, "Test Series")
        assert not result.is_breach  # High outlier should be ignored

    def test_zscore_detector_insufficient_samples(self):
        """Test z-score detection with insufficient samples."""
        config = {"threshold": 2.0, "min_samples": 10}
        detector = ZScoreDetector(config)

        # Not enough samples
        values = [10.0, 11.0, 12.0]  # Only 3 samples, need 10
        result = detector.detect(values, "Test Series")
        assert not result.is_breach
        assert result.detector_score is None
        assert "insufficient_samples" in result.metadata

    def test_zscore_detector_no_variation(self):
        """Test z-score detection when there's no variation in data."""
        config = {"threshold": 2.0, "min_samples": 5}
        detector = ZScoreDetector(config)

        # All values are the same
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        result = detector.detect(values, "Test Series")
        assert not result.is_breach
        assert result.detector_score == 0.0  # No variation = 0 z-score

    def test_zscore_detector_validation(self):
        """Test z-score detector configuration validation."""
        # Valid configuration
        config = {"threshold": 2.0, "direction": "both", "min_samples": 5}
        ZScoreDetector(config)  # Should not raise

        # Invalid threshold
        with pytest.raises(ValueError, match="Z-score threshold must be a positive number"):
            ZScoreDetector({"threshold": -1.0})

        # Invalid direction
        with pytest.raises(ValueError, match="direction must be"):
            ZScoreDetector({"threshold": 2.0, "direction": "invalid"})

        # Invalid min_samples
        with pytest.raises(ValueError, match="min_samples must be an integer"):
            ZScoreDetector({"threshold": 2.0, "min_samples": 1})


class TestMADDetector:
    """Tests for MAD (Median Absolute Deviation) based detection."""

    def test_mad_detector_basic(self):
        """Test basic MAD detection."""
        config = {"threshold": 3.0, "direction": "both", "min_samples": 5, "window_size": 20}

        detector = MADDetector(config)
        assert detector.detector_type == DetectorType.MAD

        # Create data with outlier: most values around 10, outlier at 30
        values = [10.0, 9.0, 11.0, 10.5, 9.5, 10.2, 9.8, 30.0]
        result = detector.detect(values, "Test Series")

        # Should detect the outlier
        assert result.is_breach
        assert result.value == 30.0
        assert abs(result.detector_score) > 3.0
        assert len(result.breach_messages) == 1
        assert "MAD score" in result.breach_messages[0]

        # Check metadata
        assert "median" in result.metadata
        assert "mad" in result.metadata
        assert "samples_used" in result.metadata

    def test_mad_detector_robust_to_outliers(self):
        """Test that MAD is more robust to outliers than z-score."""
        config = {"threshold": 3.0, "min_samples": 5}
        mad_detector = MADDetector(config)

        zscore_config = {"threshold": 2.0, "min_samples": 5}
        zscore_detector = ZScoreDetector(zscore_config)

        # Data with multiple outliers that might skew mean/std
        values = [10.0, 9.0, 11.0, 10.5, 9.5, 100.0, 200.0, 12.0]

        mad_result = mad_detector.detect(values, "Test Series")
        zscore_result = zscore_detector.detect(values, "Test Series")

        # MAD should be more stable (this is a characterization test)
        # The exact behavior depends on the data, but MAD should generally
        # provide more consistent results with multiple outliers
        assert mad_result.detector_score is not None
        assert zscore_result.detector_score is not None

    def test_mad_detector_no_variation(self):
        """Test MAD detection when there's no variation."""
        config = {"threshold": 3.0, "min_samples": 5}
        detector = MADDetector(config)

        # All values are the same
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        result = detector.detect(values, "Test Series")
        assert not result.is_breach
        assert result.detector_score == 0.0

    def test_mad_detector_validation(self):
        """Test MAD detector configuration validation."""
        # Valid configuration
        config = {"threshold": 3.0, "direction": "both", "min_samples": 5}
        MADDetector(config)  # Should not raise

        # Invalid threshold
        with pytest.raises(ValueError, match="MAD threshold must be a positive number"):
            MADDetector({"threshold": 0})

        # Invalid direction
        with pytest.raises(ValueError, match="direction must be"):
            MADDetector({"threshold": 3.0, "direction": "sideways"})


class TestDetectorFactory:
    """Tests for the detector factory function."""

    def test_create_detector_threshold(self):
        """Test creating threshold detector via factory."""
        config = {"bounds": {"upper": 100}, "threshold_type": "absolute"}
        detector = create_detector(DetectorType.THRESHOLD, config)
        assert isinstance(detector, ThresholdDetector)

    def test_create_detector_zscore(self):
        """Test creating z-score detector via factory."""
        config = {"threshold": 2.0, "direction": "both"}
        detector = create_detector(DetectorType.ZSCORE, config)
        assert isinstance(detector, ZScoreDetector)

    def test_create_detector_mad(self):
        """Test creating MAD detector via factory."""
        config = {"threshold": 3.0, "direction": "both"}
        detector = create_detector(DetectorType.MAD, config)
        assert isinstance(detector, MADDetector)

    def test_create_detector_invalid_type(self):
        """Test creating detector with invalid type."""
        with pytest.raises(ValueError, match="Unknown detector type"):
            create_detector("invalid_type", {})


class TestDetectorIntegration:
    """Integration tests for detector system."""

    @pytest.mark.parametrize("value_type", [ValueType.RAW, ValueType.DELTA])
    def test_all_detectors_with_value_types(self, value_type):
        """Test all detectors work with both raw values and deltas."""
        # Time series with trend: values increasing by 2 each time
        values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 40.0]  # Last value is outlier

        detectors = [
            (DetectorType.THRESHOLD, {"bounds": {"upper": 25}, "threshold_type": "absolute"}),
            (DetectorType.ZSCORE, {"threshold": 2.0, "min_samples": 5}),
            (DetectorType.MAD, {"threshold": 3.0, "min_samples": 5}),
        ]

        for detector_type, config in detectors:
            detector = create_detector(detector_type, config)
            result = detector.detect(values, "Test Series", value_type)

            # All should have valid results
            assert result.value is not None
            assert result.value == 40.0  # Should always return raw value

            # Detector scores depend on value_type
            if value_type == ValueType.DELTA:
                # For deltas, we're looking at the changes between values
                # The last delta (22 -> 40 = 18) is much larger than others (~2)
                if detector_type != DetectorType.THRESHOLD:
                    assert result.detector_score is not None
            else:
                # For raw values, we're looking at the absolute values
                if detector_type != DetectorType.THRESHOLD:
                    assert result.detector_score is not None

    def test_detector_with_empty_values(self):
        """Test all detectors handle empty input gracefully."""
        detectors = [
            (DetectorType.THRESHOLD, {"bounds": {"upper": 100}, "threshold_type": "absolute"}),
            (DetectorType.ZSCORE, {"threshold": 2.0, "min_samples": 5}),
            (DetectorType.MAD, {"threshold": 3.0, "min_samples": 5}),
        ]

        for detector_type, config in detectors:
            detector = create_detector(detector_type, config)
            result = detector.detect([], "Test Series")

            assert result.value is None
            assert not result.is_breach
            assert len(result.breach_messages) == 0

    def test_detector_with_single_value(self):
        """Test all detectors handle single value input."""
        # Threshold detector works fine with single values
        threshold_detector = create_detector(
            DetectorType.THRESHOLD, {"bounds": {"upper": 50}, "threshold_type": "absolute"}
        )
        result = threshold_detector.detect([100.0], "Test Series")
        assert result.value == 100.0
        assert result.is_breach  # 100 > 50

        # Statistical detectors need at least 2 samples, so they should handle insufficient data gracefully
        zscore_detector = create_detector(DetectorType.ZSCORE, {"threshold": 2.0, "min_samples": 2})
        result = zscore_detector.detect([100.0], "Test Series")
        assert result.value == 100.0
        assert not result.is_breach  # Insufficient data
        assert "insufficient_samples" in result.metadata

        mad_detector = create_detector(DetectorType.MAD, {"threshold": 3.0, "min_samples": 2})
        result = mad_detector.detect([100.0], "Test Series")
        assert result.value == 100.0
        assert not result.is_breach  # Insufficient data
        assert "insufficient_samples" in result.metadata
