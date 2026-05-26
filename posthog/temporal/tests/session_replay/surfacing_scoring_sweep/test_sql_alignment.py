"""CI guard: fetch_features_sql(), FEATURE_RANGES, and model.ubj stay aligned."""

from __future__ import annotations

from pathlib import Path

import pytest

import xgboost as xgb

from posthog.temporal.session_replay.surfacing_scoring_sweep import scorer as scorer_mod
from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import (
    assert_booster_matches_sql,
    assert_serving_schema_parity,
    assert_sql_matches_feature_ranges,
    get_sql_feature_names,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import feature_columns_in_select, fetch_features_sql


@pytest.fixture(scope="module")
def bundled_model_path() -> Path:
    path = Path(scorer_mod._BUNDLED_MODEL_PATH)
    if not path.exists():
        pytest.fail(
            f"Bundled model file not found at {path}. The pipeline ships with "
            "a checked-in model.ubj — regenerate it with "
            "`python bin/generate_surfacing_placeholder_model.py`."
        )
    return path


@pytest.fixture(scope="module")
def bundled_booster_feature_names(bundled_model_path: Path) -> tuple[str, ...]:
    booster = xgb.Booster()
    booster.load_model(str(bundled_model_path))
    names = tuple(booster.feature_names or ())
    if not names:
        pytest.fail(
            f"Bundled booster at {bundled_model_path} has no feature_names. "
            "Retrain and pass feature_names= to xgb.DMatrix."
        )
    return names


class TestServingFeatureSchemaParity:
    def test_sql_select_aliases_match_feature_ranges(self) -> None:
        assert_sql_matches_feature_ranges()

    def test_sql_select_aliases_match_booster_feature_names(
        self, bundled_booster_feature_names: tuple[str, ...]
    ) -> None:
        assert_booster_matches_sql(bundled_booster_feature_names)

    def test_full_serving_schema_parity(self, bundled_booster_feature_names: tuple[str, ...]) -> None:
        assert_serving_schema_parity(bundled_booster_feature_names)

    def test_feature_ranges_is_exactly_booster_features(self, bundled_booster_feature_names: tuple[str, ...]) -> None:
        extra = set(FEATURE_RANGES.keys()) - set(bundled_booster_feature_names)
        assert not extra, (
            f"FEATURE_RANGES has {len(extra)} entries not declared by the bundled booster: "
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
