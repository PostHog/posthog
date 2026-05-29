import pytest

from posthog.models.pulse import SENSITIVITY_PRESETS, DetectionMode, Sensitivity


class TestPulseEnums:
    def test_detection_mode_values(self):
        assert DetectionMode.CHANGE_V1 == "change_v1"
        assert DetectionMode.DISCOVERY == "discovery"

    def test_sensitivity_values(self):
        assert Sensitivity.CONSERVATIVE == "conservative"
        assert Sensitivity.BALANCED == "balanced"
        assert Sensitivity.SENSITIVE == "sensitive"
        assert Sensitivity.CUSTOM == "custom"

    @pytest.mark.parametrize(
        "sensitivity,expected_min_change_pct,expected_robust_z",
        [
            (Sensitivity.CONSERVATIVE, 0.40, 3.5),
            (Sensitivity.BALANCED, 0.25, 3.5),
            (Sensitivity.SENSITIVE, 0.15, 3.0),
        ],
    )
    def test_sensitivity_presets_resolve(self, sensitivity, expected_min_change_pct, expected_robust_z):
        min_change_pct, robust_z = SENSITIVITY_PRESETS[sensitivity]
        assert min_change_pct == expected_min_change_pct
        assert robust_z == expected_robust_z

    def test_custom_has_no_preset_entry(self):
        assert Sensitivity.CUSTOM not in SENSITIVITY_PRESETS
