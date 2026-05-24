"""Keep ClickHouse SQL, FEATURE_RANGES, and the XGBoost booster in sync.

Three artifacts define the serving feature schema:

    1. ``fetch_features_sql()`` — final SELECT aliases (what ClickHouse returns)
    2. ``FEATURE_RANGES`` — per-feature dtype/range contracts for ``validate_features``
    3. ``booster.feature_names`` — model input column order from the trained ``.ubj``

Drift between any pair silently mis-scores sessions or crashes chunks at runtime.
This module centralises the parity checks so drift is caught at worker boot and
in CI instead of on the first production tick.

Check layers (weakest → strongest):

    * SQL ↔ FEATURE_RANGES — pure Python, no model file; runs on every worker boot
    * booster ↔ FEATURE_RANGES — ``assert_ranges_cover`` inside ``_load_booster``
    * booster ↔ SQL — runs when the booster loads; requires a model whose
      ``feature_names`` match the SELECT alias list
"""

from __future__ import annotations

from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES, assert_ranges_cover
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import feature_columns_in_select, fetch_features_sql


class FeatureSchemaDriftError(Exception):
    """Serving artifacts disagree on the feature column set or order."""


def get_sql_feature_names() -> tuple[str, ...]:
    """Return feature column aliases from ``fetch_features_sql()`` in SELECT order."""
    names = feature_columns_in_select(fetch_features_sql())
    if not names:
        raise FeatureSchemaDriftError(
            "Could not parse feature aliases from fetch_features_sql(). "
            "The final SELECT must list `<rf>.<feature>` columns one per line."
        )
    return names


def assert_sql_matches_feature_ranges() -> None:
    """Hard-fail if SQL SELECT aliases diverge from ``FEATURE_RANGES`` keys."""
    sql_names = get_sql_feature_names()
    range_names = tuple(FEATURE_RANGES.keys())
    if sql_names != range_names:
        raise FeatureSchemaDriftError(
            "fetch_features_sql() drifted from FEATURE_RANGES.\n"
            f"  SQL aliases ({len(sql_names)}): {list(sql_names)}\n"
            f"  FEATURE_RANGES ({len(range_names)}): {list(range_names)}\n"
            f"  In SQL not ranges: {sorted(set(sql_names) - set(range_names))}\n"
            f"  In ranges not SQL: {sorted(set(range_names) - set(sql_names))}\n"
            "Update sql.py and features.py together, then bump MODEL_FEATURE_SCHEMA_VERSION."
        )


def assert_booster_matches_sql(booster_names: tuple[str, ...]) -> None:
    """Hard-fail if the booster's ``feature_names`` diverge from the SQL SELECT."""
    if not booster_names:
        raise FeatureSchemaDriftError(
            "Booster has no feature_names. Train with explicit feature_names= on xgb.DMatrix."
        )
    sql_names = get_sql_feature_names()
    if booster_names != sql_names:
        raise FeatureSchemaDriftError(
            "Booster feature_names drifted from fetch_features_sql().\n"
            f"  SQL aliases ({len(sql_names)}): {list(sql_names)}\n"
            f"  Booster names ({len(booster_names)}): {list(booster_names)}\n"
            f"  In SQL not booster: {sorted(set(sql_names) - set(booster_names))}\n"
            f"  In booster not SQL: {sorted(set(booster_names) - set(sql_names))}\n"
            "Either retrain the model against the current SQL or update fetch_features_sql()."
        )


def assert_serving_schema_parity(booster_names: tuple[str, ...]) -> None:
    """Run all serving-schema parity checks (SQL ↔ ranges ↔ booster)."""
    assert_sql_matches_feature_ranges()
    assert_ranges_cover(booster_names)
    assert_booster_matches_sql(booster_names)
