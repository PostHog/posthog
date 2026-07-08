"""CI guard: fetch_features_sql(), FEATURE_RANGES, and a synthetic booster stay aligned.

Prod model lives in S3; `assert_serving_schema_parity` re-runs at worker boot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import xgboost as xgb

from posthog.temporal.session_replay.surfacing_scoring_sweep.feature_schema import (
    FeatureSchemaDriftError,
    assert_booster_matches_sql,
    assert_serving_schema_parity,
    assert_sql_matches_feature_ranges,
    get_sql_feature_names,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import feature_columns_in_select, fetch_features_sql
from posthog.temporal.tests.session_replay.surfacing_scoring_sweep.conftest import train_synthetic_booster


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

    def test_every_feature_range_entry_is_produced_by_sql(self) -> None:
        # FEATURE_RANGES is the documented universe of serving features; every
        # entry must be a real SQL column (no stale entries). The booster is
        # allowed to use a subset of these — that's covered below.
        missing = set(FEATURE_RANGES.keys()) - set(get_sql_feature_names())
        assert not missing, f"FEATURE_RANGES has entries the SQL never produces: {sorted(missing)}"

    def test_strict_subset_booster_passes_parity(self) -> None:
        # The production booster is simpler than the serving query: it scores a
        # proper subset of the SQL's feature columns. The parity gate must
        # accept that — the whole point of the superset contract.
        sql_names = get_sql_feature_names()
        subset = sql_names[::2]
        assert set(subset) < set(sql_names), "test setup: subset must be proper"
        booster = train_synthetic_booster(subset)
        assert_serving_schema_parity(tuple(booster.feature_names or ()))

    def test_booster_needing_unknown_feature_fails_parity(self) -> None:
        # A booster that needs a column the SQL never produces is fatal drift.
        booster = train_synthetic_booster((*get_sql_feature_names()[:4], "feature_the_sql_never_produces"))
        with pytest.raises(FeatureSchemaDriftError, match="does not produce"):
            assert_booster_matches_sql(tuple(booster.feature_names or ()))


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
