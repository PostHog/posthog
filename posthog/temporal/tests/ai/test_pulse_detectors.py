import pytest

from posthog.temporal.ai.pulse.detectors import DetectionResult, PulseDetector, get_detector, register_detector
from posthog.temporal.ai.pulse.types import DetectChangesInputs, EnrichedFinding, Finding


class TestDetectorRegistry:
    def test_get_detector_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown detection mode: nope"):
            get_detector("nope")

    def test_get_detector_returns_change_v1(self):
        detector = get_detector("change_v1")
        assert isinstance(detector, PulseDetector)

    def test_register_detector_adds_to_registry(self):
        @register_detector("test_only_mode")
        class _Dummy(PulseDetector):
            def detect(self, current, baseline, min_change_pct, robust_z_threshold):
                return DetectionResult(
                    triggered=False,
                    baseline_median=0.0,
                    change_pct=0.0,
                    impact=0.0,
                    robust_z=0.0,
                )

        assert isinstance(get_detector("test_only_mode"), _Dummy)

    def test_detection_result_fields(self):
        result = DetectionResult(
            triggered=True,
            baseline_median=100.0,
            change_pct=-0.5,
            impact=5.0,
            robust_z=3.2,
        )
        assert result.triggered is True
        assert result.baseline_median == 100.0
        assert result.impact == 5.0
        assert result.robust_z == 3.2


class TestNoStaleZScoreReferences:
    def test_finding_has_no_z_score_field(self):
        assert "z_score" not in Finding.model_fields
        assert "robust_z" in Finding.model_fields
        assert "impact" in Finding.model_fields
        assert "z_score" not in EnrichedFinding.model_fields
        assert "robust_z" in EnrichedFinding.model_fields
        assert "impact" in EnrichedFinding.model_fields

    def test_detect_changes_inputs_uses_robust_z_threshold(self):
        assert "z_threshold" not in DetectChangesInputs.model_fields
        assert "robust_z_threshold" in DetectChangesInputs.model_fields
