"""CI guard: fetch_features_sql(), FEATURE_RANGES, and a synthetic booster stay aligned.

Prod model lives in S3; `assert_serving_schema_parity` re-runs at worker boot.
"""

from __future__ import annotations

from pathlib import Path

import xgboost as xgb

from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import (
    assert_booster_matches_sql,
    assert_serving_schema_parity,
    assert_sql_matches_feature_ranges,
    get_sql_feature_names,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import feature_columns_in_select, fetch_features_sql


def _feature_names(model_path: Path) -> tuple[str, ...]:
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    return tuple(booster.feature_names or ())


class TestServingFeatureSchemaParity:
    def test_sql_select_aliases_match_feature_ranges(self) -> None:
        assert_sql_matches_feature_ranges()

    def test_sql_select_aliases_match_booster_feature_names(self, surfacing_booster_path: Path) -> None:
        assert_booster_matches_sql(_feature_names(surfacing_booster_path))

    def test_full_serving_schema_parity(self, surfacing_booster_path: Path) -> None:
        assert_serving_schema_parity(_feature_names(surfacing_booster_path))

    def test_feature_ranges_is_exactly_booster_features(self, surfacing_booster_path: Path) -> None:
        booster_names = set(_feature_names(surfacing_booster_path))
        extra = set(FEATURE_RANGES.keys()) - booster_names
        assert not extra, (
            f"FEATURE_RANGES has {len(extra)} entries not declared by the booster: "
            f"{sorted(extra)}. Drop stale entries or retrain the model."
        )


class TestFeatureColumnsInSelectParser:
    """Self-tests for the regex parser that powers the parity check."""

    def test_extracts_feature_aliases_from_real_sql(self) -> None:
        aliases = get_sql_feature_names()
        assert len(aliases) > 0
        assert len(aliases) == len(set(aliases)), f"Duplicate aliases in SQL: {aliases}"

    def test_ignores_id_columns(self) -> None:
        aliases = feature_columns_in_select(fetch_features_sql())
        assert "team_id" not in aliases
        assert "session_id" not in aliases
        assert "distinct_id" not in aliases
        assert "min_first_timestamp" not in aliases

    def test_returns_empty_tuple_on_malformed_input(self) -> None:
        assert feature_columns_in_select("not a SQL statement at all") == ()

    def test_respects_alias_argument(self) -> None:
        synthetic = (
            "WITH cte AS (SELECT 1)\n"
            ") SELECT\n"
            "    e.team_id,\n"
            "    rf.feature_a,\n"
            "    other.ignored,\n"
            "    rf.feature_b\n"
            "FROM eligible_sessions e"
        )
        assert feature_columns_in_select(synthetic, feature_table_alias="rf") == ("feature_a", "feature_b")
        assert feature_columns_in_select(synthetic, feature_table_alias="other") == ("ignored",)
