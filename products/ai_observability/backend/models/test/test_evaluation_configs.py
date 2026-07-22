import pytest

from products.ai_observability.backend.models.evaluation_configs import validate_target_config


class TestValidateTargetConfig:
    @pytest.mark.parametrize(
        "config,expected",
        [
            ({}, {"strategy": "fixed_window", "window_seconds": 1800}),
            (None, {"strategy": "fixed_window", "window_seconds": 1800}),
            ({"window_seconds": 60}, {"strategy": "fixed_window", "window_seconds": 60}),
            (
                {"strategy": "fixed_window", "window_seconds": 7200},
                {"strategy": "fixed_window", "window_seconds": 7200},
            ),
            (
                {"strategy": "inactivity"},
                {"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200},
            ),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 60, "max_age_seconds": 600},
                {"strategy": "inactivity", "quiet_period_seconds": 60, "max_age_seconds": 600},
            ),
        ],
    )
    def test_trace_configs_normalize(self, config, expected):
        assert validate_target_config("trace", config) == expected

    @pytest.mark.parametrize(
        "config",
        [
            {"window_seconds": 5},
            {"window_seconds": 7201},
            {"strategy": "inactivity", "quiet_period_seconds": 5},
            {"strategy": "inactivity", "quiet_period_seconds": 1801},
            {"strategy": "inactivity", "max_age_seconds": 30},
            {"strategy": "inactivity", "quiet_period_seconds": 600, "max_age_seconds": 300},
            {"strategy": "inactivity", "window_seconds": 100},
            {"strategy": "fixed_window", "quiet_period_seconds": 100},
            {"strategy": "sliding"},
            {"unknown_key": 1},
        ],
    )
    def test_invalid_trace_configs_rejected(self, config):
        with pytest.raises(ValueError):
            validate_target_config("trace", config)

    def test_generation_strips_config(self):
        assert validate_target_config("generation", {"strategy": "inactivity"}) == {}
