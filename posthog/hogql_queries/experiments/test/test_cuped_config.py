from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric

from posthog.hogql_queries.experiments.cuped_config import DEFAULT_CUPED_LOOKBACK_DAYS, get_cuped_config


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
