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


class TestValidateSessionTargetConfig:
    @pytest.mark.parametrize(
        "config,expected",
        [
            # No strategy means inactivity for sessions, unlike traces. There are no legacy
            # strategy-less session rows, so nothing needs fixed_window back-compat here.
            ({}, {"strategy": "inactivity", "quiet_period_seconds": 3600, "max_age_seconds": 86400}),
            (None, {"strategy": "inactivity", "quiet_period_seconds": 3600, "max_age_seconds": 86400}),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 86400, "max_age_seconds": 604800},
                {"strategy": "inactivity", "quiet_period_seconds": 86400, "max_age_seconds": 604800},
            ),
            (
                {"strategy": "fixed_window", "window_seconds": 604800},
                {"strategy": "fixed_window", "window_seconds": 604800},
            ),
        ],
    )
    def test_session_configs_normalize(self, config, expected):
        assert validate_target_config("session", config) == expected

    @pytest.mark.parametrize(
        "config",
        [
            {"strategy": "inactivity", "quiet_period_seconds": 86401},
            {"strategy": "inactivity", "max_age_seconds": 604801},
            {"strategy": "inactivity", "quiet_period_seconds": 5},
            {"strategy": "inactivity", "quiet_period_seconds": 7200, "max_age_seconds": 3600},
            {"strategy": "fixed_window", "window_seconds": 604801},
            {"strategy": "sliding"},
            {"unknown_key": 1},
        ],
    )
    def test_invalid_session_configs_rejected(self, config):
        with pytest.raises(ValueError):
            validate_target_config("session", config)

    @pytest.mark.parametrize(
        "target,config",
        [
            ("trace", {"strategy": "inactivity", "quiet_period_seconds": 86400}),
            ("trace", {"strategy": "inactivity", "max_age_seconds": 604800}),
            ("trace", {"strategy": "fixed_window", "window_seconds": 604800}),
        ],
    )
    def test_session_sized_values_rejected_for_trace(self, target, config):
        """The widened OpenAPI range lets a client send these; the server is the enforcement point."""
        with pytest.raises(ValueError):
            validate_target_config(target, config)
