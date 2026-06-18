"""Unit tests for `surfacing_scoring_sweep.features.validate_features`.

The function is the runtime gate between the CH SELECT and the XGBoost
predict — every drift mode that could mis-score sessions in production is
covered here. Tests are pure pandas, no CH or xgboost in the picture.

`validate_features` and `feature_matrix` take `feature_names` explicitly, so
these tests don't need a real booster — they pass the test fixture's
`feature_names_for_tests` (= `FEATURE_RANGES.keys()`).
"""

from __future__ import annotations

from typing import Any

import pytest

import numpy as np
import pandas as pd

from posthog.temporal.session_replay.surfacing_scoring_sweep.features import (
    FEATURE_RANGES,
    FeatureValidationError,
    MissingFeatureRangeError,
    assert_ranges_cover,
    feature_matrix,
    out_of_contract_row_mask,
    validate_features,
)


class TestValidateFeaturesHappyPaths:
    def test_zero_row_dataframe_passes(self, feature_names_for_tests: tuple[str, ...]) -> None:
        row = dict.fromkeys(feature_names_for_tests, 0.0)
        validate_features(pd.DataFrame([row]), feature_names=feature_names_for_tests)

    def test_empty_dataframe_passes(self, feature_names_for_tests: tuple[str, ...]) -> None:
        validate_features(
            pd.DataFrame(columns=pd.Index(feature_names_for_tests)),
            feature_names=feature_names_for_tests,
        )

    def test_nan_passes_for_float_features(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # XGBoost handles NaN natively; our SQL deliberately produces NULL → NaN
        # when denominators are zero. NaN must not be rejected.
        feature_frame.loc[0, "event_rate"] = float("nan")
        feature_frame.loc[1, "mouse_mean_x"] = float("nan")
        validate_features(feature_frame, feature_names=feature_names_for_tests)

    def test_id_columns_alongside_features_pass(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # The CH SELECT returns id columns + features in one frame. validate_features
        # must accept that layout, not just bare features.
        df = feature_frame.copy()
        df["team_id"] = 42
        df["session_id"] = "00000000-0000-7000-0000-000000000000"
        df["distinct_id"] = "user-1"
        df["min_first_timestamp"] = pd.Timestamp("2026-01-01")
        validate_features(df, feature_names=feature_names_for_tests)


class TestValidateFeaturesColumnSet:
    def test_missing_column_raises(self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]) -> None:
        df = feature_frame.drop(columns=["click_rate"])
        with pytest.raises(FeatureValidationError, match=r"missing=\['click_rate'\]"):
            validate_features(df, feature_names=feature_names_for_tests)

    def test_extra_feature_column_is_tolerated(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # The serving SQL may expose a superset of columns; the booster scores
        # its own subset (feature_matrix selects by name), so extra columns the
        # booster ignores must not fail the chunk.
        df = feature_frame.copy()
        df["unused_extra_feature"] = 0.0
        validate_features(df, feature_names=feature_names_for_tests)

    def test_subset_booster_validates_against_superset_frame(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Models the production case: a simpler booster (a subset of the
        # query's features) scored against the full feature frame.
        subset = feature_names_for_tests[: len(feature_names_for_tests) // 2]
        validate_features(feature_frame, feature_names=subset)

    def test_reordered_columns_are_tolerated(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Column order is irrelevant: feature_matrix reorders to the trained
        # order by name before DMatrix construction.
        cols = list(feature_frame.columns)
        cols[0], cols[1] = cols[1], cols[0]
        validate_features(feature_frame.loc[:, cols], feature_names=feature_names_for_tests)


class TestOutOfContractRowMask:
    @pytest.mark.parametrize(
        ("column", "bad_value"),
        [
            ("event_rate", -0.5),
            ("network_failure_ratio", 1.5),
            ("page_revisit_share", 1.5),
            ("mouse_stddev_x", -1.0),
            ("selection_copy_count", -1),
            ("event_rate", float("inf")),
            ("event_rate", float("-inf")),
        ],
    )
    def test_out_of_contract_value_flags_only_its_row(
        self,
        column: str,
        bad_value: Any,
        feature_frame: pd.DataFrame,
        feature_names_for_tests: tuple[str, ...],
    ) -> None:
        good_row = feature_frame.iloc[0].copy()
        df = pd.DataFrame([feature_frame.iloc[0], good_row]).reset_index(drop=True)
        df.loc[0, column] = bad_value

        mask = out_of_contract_row_mask(df, feature_names=feature_names_for_tests)

        assert mask.tolist() == [True, False]

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            # Rates have no upper bound — high counts on short sessions can produce
            # arbitrarily large rates. Don't false-positive on legitimate data.
            ("event_rate", 1e6),
            # mouse_mean_x has no lower bound — mouse can be off-screen.
            ("mouse_mean_x", -1234.5),
            # NaN passes — XGBoost handles it natively, SQL produces NULL on zero denominators.
            ("network_failure_ratio", float("nan")),
        ],
    )
    def test_in_contract_value_is_not_flagged(
        self,
        column: str,
        value: float,
        feature_frame: pd.DataFrame,
        feature_names_for_tests: tuple[str, ...],
    ) -> None:
        feature_frame.loc[0, column] = value

        mask = out_of_contract_row_mask(feature_frame, feature_names=feature_names_for_tests)

        assert not mask.any()


class TestValidateFeaturesDtypes:
    def test_string_dtype_rejected_for_numeric_feature(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        df = feature_frame.copy()
        df["event_rate"] = df["event_rate"].astype(str)
        with pytest.raises(FeatureValidationError, match="dtype"):
            validate_features(df, feature_names=feature_names_for_tests)

    def test_int_dtype_accepted_for_count_column(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Count columns can come back as int64 (no NULLs) or float64 (some NULLs)
        # depending on what's in the chunk — both must pass.
        df = feature_frame.copy()
        df["selection_copy_count"] = df["selection_copy_count"].astype(np.int64)
        validate_features(df, feature_names=feature_names_for_tests)

    def test_float_dtype_accepted_for_count_column(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        df = feature_frame.copy()
        df["selection_copy_count"] = df["selection_copy_count"].astype(np.float64)
        validate_features(df, feature_names=feature_names_for_tests)


class TestFeatureMatrix:
    def test_strips_id_columns(self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]) -> None:
        df = feature_frame.copy()
        df["team_id"] = 1
        df["session_id"] = "00000000-0000-7000-0000-000000000000"
        df["distinct_id"] = "user-1"
        df["min_first_timestamp"] = pd.Timestamp("2026-01-01")

        out = feature_matrix(df, feature_names=feature_names_for_tests)

        assert list(out.columns) == list(feature_names_for_tests)
        assert "team_id" not in out.columns
        assert "session_id" not in out.columns
        assert "distinct_id" not in out.columns
        assert "min_first_timestamp" not in out.columns
        assert len(out) == len(feature_frame)

    def test_preserves_row_order(self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]) -> None:
        # Predict re-attaches scores positionally — a row reorder here would
        # cross-write scores to the wrong sessions.
        out = feature_matrix(feature_frame, feature_names=feature_names_for_tests)
        first = feature_names_for_tests[0]
        pd.testing.assert_series_equal(out[first], feature_frame[first])

    def test_reorders_to_trained_order(
        self, feature_frame: pd.DataFrame, feature_names_for_tests: tuple[str, ...]
    ) -> None:
        # Even if the input frame has features in a different order (e.g. CH
        # returns them in a different sequence after a refactor), feature_matrix
        # must hand back columns in the trained order so DMatrix construction
        # is consistent.
        shuffled_cols = list(reversed(feature_names_for_tests))
        out = feature_matrix(feature_frame.loc[:, shuffled_cols], feature_names=feature_names_for_tests)
        assert list(out.columns) == list(feature_names_for_tests)


class TestAssertRangesCover:
    def test_passes_when_every_name_has_a_range(self) -> None:
        # The test fixture is exactly `FEATURE_RANGES.keys()` — should always pass.
        assert_ranges_cover(tuple(FEATURE_RANGES.keys()))

    def test_passes_for_subset_of_ranges(self) -> None:
        # A retrained booster might use fewer features than `FEATURE_RANGES`
        # covers (e.g. dropped a low-importance one). Only "missing" coverage
        # is an error; "extra" range entries are dead-but-harmless.
        first_three = tuple(list(FEATURE_RANGES.keys())[:3])
        assert_ranges_cover(first_three)

    def test_raises_when_booster_declares_uncovered_feature(self) -> None:
        # Booster ships with a name that has no FEATURE_RANGES entry → operator
        # forgot to add the runtime range contract for the new feature.
        with pytest.raises(MissingFeatureRangeError, match="bogus_new_feature"):
            assert_ranges_cover(("event_rate", "bogus_new_feature"))

    def test_raises_when_booster_has_no_feature_names(self) -> None:
        # Model was trained without explicit feature_names — serving cannot
        # match SELECT aliases against a nameless schema.
        with pytest.raises(MissingFeatureRangeError, match="no feature_names"):
            assert_ranges_cover(())
