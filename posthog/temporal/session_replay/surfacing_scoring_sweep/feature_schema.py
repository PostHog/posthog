"""Parity checks for fetch_features_sql(), FEATURE_RANGES, and booster.feature_names."""

from __future__ import annotations

from posthog.temporal.session_replay.surfacing_scoring_sweep.features import FEATURE_RANGES, assert_ranges_cover
from posthog.temporal.session_replay.surfacing_scoring_sweep.sql import feature_columns_in_select, fetch_features_sql


class FeatureSchemaDriftError(Exception):
    """Serving artifacts disagree on the feature column set or order."""


def get_sql_feature_names() -> tuple[str, ...]:
    """Feature column aliases from fetch_features_sql() in SELECT order."""
    names = feature_columns_in_select(fetch_features_sql())
    if not names:
        raise FeatureSchemaDriftError(
            "Could not parse feature aliases from fetch_features_sql(). "
            "The final SELECT must list `<rf>.<feature>` columns one per line."
        )
    return names


def assert_sql_matches_feature_ranges() -> None:
    """Hard-fail if SQL aliases diverge from FEATURE_RANGES keys."""
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
    """Hard-fail if the booster needs a feature the SQL doesn't produce.

    The booster is the source of truth for *which* features the model scores;
    the serving SQL must produce a superset of them (it may expose extra
    columns the booster ignores — `feature_matrix` selects the booster's by
    name). The only fatal drift is a booster feature the SQL never produces.
    """
    if not booster_names:
        raise FeatureSchemaDriftError(
            "Booster has no feature_names. Train with explicit feature_names= on xgb.DMatrix."
        )
    sql_names = get_sql_feature_names()
    not_produced = [name for name in booster_names if name not in set(sql_names)]
    if not_produced:
        raise FeatureSchemaDriftError(
            "Booster needs feature(s) fetch_features_sql() does not produce.\n"
            f"  SQL aliases ({len(sql_names)}): {list(sql_names)}\n"
            f"  Booster names ({len(booster_names)}): {list(booster_names)}\n"
            f"  In booster not SQL: {sorted(not_produced)}\n"
            "Add these columns to fetch_features_sql() (and FEATURE_RANGES), or retrain."
        )


def assert_serving_schema_parity(booster_names: tuple[str, ...]) -> None:
    """Run SQL ↔ FEATURE_RANGES ↔ booster parity checks."""
    assert_sql_matches_feature_ranges()
    assert_ranges_cover(booster_names)
    assert_booster_matches_sql(booster_names)
