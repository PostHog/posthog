from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric

from posthog.hogql_queries.experiments.cuped_config import (
    DEFAULT_CUPED_LOOKBACK_DAYS,
    MAX_CUPED_LOOKBACK_DAYS,
    MIN_CUPED_LOOKBACK_DAYS,
    get_cuped_config,
)


def _supported_metric() -> ExperimentMeanMetric:
    return ExperimentMeanMetric(source=EventsNode(event="purchase"))


@parameterized.expand(
    [
        # (name, stats_config, team_default_enabled, expected_enabled)
        ("no_stats_config_no_team_default", None, False, False),
        ("no_stats_config_team_default_enabled", None, True, True),
        ("empty_cuped_dict_uses_team_default", {"cuped": {}}, True, True),
        ("missing_cuped_key_uses_team_default", {"method": "bayesian"}, True, True),
        ("experiment_explicit_true_with_team_false", {"cuped": {"enabled": True}}, False, True),
        ("experiment_explicit_false_overrides_team_true", {"cuped": {"enabled": False}}, True, False),
        ("experiment_explicit_true_with_team_true", {"cuped": {"enabled": True}}, True, True),
    ]
)
def test_get_cuped_config_priority(name, stats_config, team_default_enabled, expected_enabled):
    config = get_cuped_config(stats_config, _supported_metric(), team_default_enabled=team_default_enabled)
    assert config.enabled is expected_enabled


def test_get_cuped_config_uses_experiment_lookback_days_when_explicitly_enabled():
    config = get_cuped_config(
        {"cuped": {"enabled": True, "lookback_days": 7}},
        _supported_metric(),
        team_default_enabled=False,
    )
    assert config.enabled is True
    assert config.lookback_days == 7


def test_get_cuped_config_uses_default_lookback_days_when_team_enables():
    config = get_cuped_config(None, _supported_metric(), team_default_enabled=True)
    assert config.enabled is True
    assert config.lookback_days == DEFAULT_CUPED_LOOKBACK_DAYS


def test_get_cuped_config_team_default_ignored_when_metric_unsupported():
    # An object that's neither ExperimentMeanMetric nor ExperimentFunnelMetric is unsupported.
    config = get_cuped_config(None, object(), team_default_enabled=True)
    assert config.enabled is False


@parameterized.expand(
    [
        # (name, stats_config, team_default_lookback_days, expected_lookback_days)
        ("no_team_default_uses_hardcoded", None, None, DEFAULT_CUPED_LOOKBACK_DAYS),
        ("team_default_used_when_no_experiment_setting", None, 7, 7),
        ("experiment_lookback_wins_over_team_default", {"cuped": {"enabled": True, "lookback_days": 21}}, 7, 21),
        (
            "team_default_used_when_experiment_has_cuped_but_no_lookback",
            {"cuped": {"enabled": True}},
            10,
            10,
        ),
        ("invalid_team_default_falls_back_to_hardcoded", None, "not-a-number", DEFAULT_CUPED_LOOKBACK_DAYS),
        ("team_default_below_min_clamps_to_min", None, 0, MIN_CUPED_LOOKBACK_DAYS),
        ("team_default_above_max_clamps_to_max", None, 1000, MAX_CUPED_LOOKBACK_DAYS),
        (
            "invalid_experiment_lookback_falls_back_to_team_default",
            {"cuped": {"enabled": True, "lookback_days": "abc"}},
            7,
            7,
        ),
        (
            "invalid_experiment_lookback_with_no_team_default_falls_back_to_hardcoded",
            {"cuped": {"enabled": True, "lookback_days": "abc"}},
            None,
            DEFAULT_CUPED_LOOKBACK_DAYS,
        ),
    ]
)
def test_get_cuped_config_lookback_days_resolution(
    name, stats_config, team_default_lookback_days, expected_lookback_days
):
    config = get_cuped_config(
        stats_config,
        _supported_metric(),
        team_default_enabled=True,
        team_default_lookback_days=team_default_lookback_days,
    )
    assert config.enabled is True
    assert config.lookback_days == expected_lookback_days
