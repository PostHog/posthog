from __future__ import annotations

from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import get_sql_feature_names
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import (
    _AGGREGATED_STATS_FRAGMENT,
    _REPLAY_FEATURES_FRAGMENT,
    fetch_features_sql,
)
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.sql_alignment_helpers import (
    feature_aliases_from_feature_select,
    load_training_query_sql,
    select_list_body,
    training_aggregated_stat_aliases,
    training_derived_feature_aliases,
)


class TestTrainingQueryAlignment:
    def test_aggregated_stats_columns_match_training_query(self) -> None:
        training = set(training_aggregated_stat_aliases())
        serving = set(feature_aliases_from_feature_select(select_list_body(_AGGREGATED_STATS_FRAGMENT)))
        assert serving - {"team_id"} == training

    def test_derived_feature_expressions_match_training_query(self) -> None:
        training = training_derived_feature_aliases()
        serving = feature_aliases_from_feature_select(_REPLAY_FEATURES_FRAGMENT)
        assert serving == training

    def test_training_fixture_includes_features_lookback_filter(self) -> None:
        sql = load_training_query_sql()
        assert "f.min_first_timestamp >= now() - INTERVAL" in sql

    def test_serving_sql_includes_features_lookback_filter(self) -> None:
        sql = fetch_features_sql()
        assert "f.min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s)" in sql

    def test_serving_feature_aliases_match_training_derived_features(self) -> None:
        assert get_sql_feature_names() == training_derived_feature_aliases()
