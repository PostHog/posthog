import math

import pytest

from products.ai_observability.backend.models.evaluation_configs import (
    NumericOutputConfig,
    NumericScoreOutOfBounds,
    validate_evaluation_configs,
    validate_target_config,
)


class TestNumericOutputConfig:
    @pytest.mark.parametrize(
        "bounds,score,expected",
        [
            ({"max": 0.7}, 7 * 0.1, 0.7),
            ({"min": -0.7}, -7 * 0.1, -0.7),
            ({"min": 0.7}, math.nextafter(0.7, -math.inf), 0.7),
            ({"max": -0.7}, math.nextafter(-0.7, math.inf), -0.7),
            ({"min": 0, "max": 1}, 0.123456789, 0.123456789),
            ({"max": 0.7}, math.nextafter(0.7, math.inf, steps=2), None),
            ({"min": -0.7}, math.nextafter(-0.7, -math.inf, steps=2), None),
            ({"max": 0.7}, 0.700001, None),
            ({"max": 1e12}, 1e12 + 1, None),
        ],
    )
    def test_score_boundary_roundoff(self, bounds, score, expected):
        config = NumericOutputConfig.model_validate(bounds)
        if expected is None:
            with pytest.raises(NumericScoreOutOfBounds):
                config.validate_score(score)
        else:
            assert config.validate_score(score) == expected

    @pytest.mark.parametrize(
        "runtime,config", [("llm_judge", {"prompt": "Score completeness"}), ("hog", {"source": "return 0;"})]
    )
    def test_numeric_configuration(self, runtime, config):
        _, output = validate_evaluation_configs(
            runtime, "numeric", config, {"min": 0, "max": 10, "passing_rule": {"operator": "gte", "threshold": 7}}
        )
        assert output == {"min": 0, "max": 10, "allows_na": False, "passing_rule": {"operator": "gte", "threshold": 7}}

    @pytest.mark.parametrize(
        "output",
        [
            {"min": 2, "max": 1},
            {"min": True},
            {"max": "10"},
            {"max": float("inf")},
            {"step": 0},
            {"step": -1},
            {"typo": 1},
            {"passing_rule": {"operator": "gt", "threshold": 0}},
            {"passing_rule": {"operator": "gte"}},
            {"passing_rule": {"operator": "gte", "threshold": True}},
            {"passing_rule": {"operator": "gte", "threshold": float("nan")}},
            {"min": 0, "passing_rule": {"operator": "gte", "threshold": -1}},
        ],
    )
    def test_invalid_numeric_configuration(self, output):
        with pytest.raises(ValueError):
            validate_evaluation_configs("hog", "numeric", {"source": "return 0;"}, output)

    def test_unbounded_and_nullable_configuration(self):
        _, output = validate_evaluation_configs(
            "hog",
            "numeric",
            {"source": "return 0;"},
            {"min": None, "max": None, "step": None, "passing_rule": None, "allows_na": True},
        )
        assert output == {"allows_na": True}


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
