"""Runtime range contract + parity validation for the session surfacing model.

The XGBoost booster is the single source of truth for *which* features the model
takes (its `.ubj` embeds `feature_names`); the worker reads them via
`scorer.get_feature_names()`, so a retrained booster updates serving with no code
change here. What stays in this module:

    * `FEATURE_RANGES`: per-feature dtype-kind + value bounds. xgboost carries no
      runtime value bounds, so this guards against "trained on [0, 1] but the SQL
      started returning 9999". Every booster feature must have an entry, else
      warmup raises `MissingFeatureRangeError`.
    * `validate_features(df, feature_names=...)`: hard gate before predict (column
      set/order + dtype). A violation can only be a wiring bug (SQL drifted from
      the booster), never bad data, so it fails the whole chunk. Pure pandas.
    * `out_of_contract_row_mask(df, feature_names=...)`: per-row flag for
      non-finite/out-of-range values. Replay payloads are client-controlled, so one
      crafted session must not fail its whole hash bucket; callers drop flagged rows
      and score the rest.

Updating features: retrain the booster, sync `FEATURE_RANGES` and
`sql.fetch_features_sql`'s alias list, bump `MODEL_FEATURE_SCHEMA_VERSION`. Drift
fails loudly: a booster feature with no range entry raises at warmup; a SQL column
mismatch raises `FeatureValidationError` on the first chunk.

Dtype notes: rates/ratios/shares are CH `Float64`; zero denominators become NaN
(XGBoost handles it; validation accepts NaN but not +/-inf). Pass-through counts
(`viewport_resize_count`, `selection_copy_count`, `unique_form_fields`) come back
as int, which pandas infers as int64 or float64 depending on NULLs; validation
accepts both.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Bump on every breaking feature-set change. Logged per chunk so distribution
# shifts can be correlated with deploys.
MODEL_FEATURE_SCHEMA_VERSION = 2

# Columns that identify the row but are NOT model features. Stripped before
# predict; re-attached for the INSERT.
ID_COLUMNS: tuple[str, ...] = ("team_id", "session_id", "distinct_id", "min_first_timestamp")

# Per-dtype-kind groupings used in `FEATURE_RANGES` below.
# `'iuf'` accepts int / unsigned int / float — useful for pass-through counts
# whose pandas dtype depends on whether NULLs are present in a given chunk.
_NUMERIC = "iuf"
_FLOAT = "f"


@dataclass(frozen=True)
class FeatureSpec:
    """Allowed dtype family + value range for a single feature.

    `dtype_kind` is one or more of numpy's dtype.kind tags concatenated
    ('i' int, 'u' unsigned int, 'f' float, 'b' bool). A range of `None` on
    either end disables that side of the bounds check.
    """

    dtype_kind: str
    min_value: float | None = None
    max_value: float | None = None


# Per-feature contracts. Bounds aren't statistical — they're the universe
# of values the model has ever been trained on. Anything outside is a wiring
# bug (negative count, infinity from a bad division), not just a distribution
# shift. Generous upper bounds are deliberate: the goal is to catch wiring
# bugs without flagging legitimate outliers.
#
# Rates: 0+, no upper bound (1k events/sec is unusual but possible).
# Ratios: 0..1 with a tiny epsilon for FP error.
# Mouse mean coords: any float (mouse can be off-screen).
# Counts: non-negative.
_RATE = FeatureSpec(_FLOAT, 0.0, None)
_RATIO = FeatureSpec(_FLOAT, 0.0, 1.0 + 1e-6)
_NONNEG_FLOAT = FeatureSpec(_FLOAT, 0.0, None)
_ANY_FLOAT = FeatureSpec(_FLOAT, None, None)
_NONNEG_COUNT = FeatureSpec(_NUMERIC, 0, None)


FEATURE_RANGES: dict[str, FeatureSpec] = {
    "event_rate": _RATE,
    "click_rate": _RATE,
    "keypress_rate": _RATE,
    "mouse_activity_rate": _RATE,
    "rage_click_rate": _RATE,
    "dead_click_rate": _RATE,
    "quick_back_rate": _RATE,
    "page_visit_rate": _RATE,
    "text_selection_rate": _RATE,
    "scroll_event_rate": _RATE,
    "console_error_rate": _RATE,
    "console_error_after_click_rate": _RATE,
    "network_request_rate": _RATE,
    "network_failed_request_rate": _RATE,
    "mouse_mean_x": _ANY_FLOAT,
    "mouse_mean_y": _ANY_FLOAT,
    "mouse_stddev_x": _NONNEG_FLOAT,
    "mouse_stddev_y": _NONNEG_FLOAT,
    "mouse_distance_per_s": _NONNEG_FLOAT,
    "mouse_direction_change_rate": _NONNEG_FLOAT,
    "mouse_velocity_mean": _NONNEG_FLOAT,
    "mouse_velocity_stddev": _NONNEG_FLOAT,
    "scroll_magnitude_per_s": _NONNEG_FLOAT,
    "scroll_magnitude_per_event": _NONNEG_FLOAT,
    "scroll_direction_reversal_rate": _RATE,
    "rapid_scroll_reversal_rate": _RATE,
    "max_scroll_y": _NONNEG_FLOAT,
    "inter_action_gap_mean_ms": _NONNEG_FLOAT,
    "inter_action_gap_stddev_ms": _NONNEG_FLOAT,
    "max_idle_gap_ms": _NONNEG_FLOAT,
    "network_request_duration_mean_ms": _NONNEG_FLOAT,
    "network_request_duration_stddev_ms": _NONNEG_FLOAT,
    "network_failure_ratio": _RATIO,
    "network_4xx_ratio": _RATIO,
    "network_5xx_ratio": _RATIO,
    "scroll_to_top_rate": _RATE,
    "backspace_ratio": _RATIO,
    "long_idle_gap_share": _RATIO,
    "console_warn_rate": _RATE,
    "mutation_rate": _RATE,
    "viewport_resize_count": _NONNEG_COUNT,
    "touch_event_rate": _RATE,
    "selection_copy_count": _NONNEG_COUNT,
    "login_path_visit_share": _RATIO,
    "signup_path_visit_share": _RATIO,
    "checkout_path_visit_share": _RATIO,
    "cart_path_visit_share": _RATIO,
    "billing_path_visit_share": _RATIO,
    "settings_path_visit_share": _RATIO,
    "account_path_visit_share": _RATIO,
    "error_path_visit_share": _RATIO,
    "not_found_path_visit_share": _RATIO,
    "admin_path_visit_share": _RATIO,
    "dashboard_path_visit_share": _RATIO,
    "onboarding_path_visit_share": _RATIO,
    "cancel_path_visit_share": _RATIO,
    "refund_path_visit_share": _RATIO,
    "unique_url_share": _RATIO,
    "click_target_share": _RATIO,
    "unique_form_fields": _NONNEG_COUNT,
    "page_revisit_share": _RATIO,
}


class FeatureValidationError(Exception):
    """Raised when a chunk's feature DataFrame doesn't match the trained schema."""


class MissingFeatureRangeError(Exception):
    """Booster declares a feature_name with no FEATURE_RANGES entry."""


def assert_ranges_cover(feature_names: Iterable[str]) -> None:
    """Hard-fail at warmup if any booster feature lacks a runtime range contract.

    Adding a new feature to the booster without adding a `FEATURE_RANGES` entry
    is a programming error: the validator wouldn't know what to bounds-check
    against, and bad CH output for the new column would slip through silently.
    Catch it once at boot, before any chunk runs.
    """
    names = tuple(feature_names)
    if not names:
        raise MissingFeatureRangeError(
            "Booster has no feature_names. Train with explicit feature_names "
            "(pass `feature_names=` to xgb.DMatrix at training time) so serving can pin its schema."
        )
    missing = [n for n in names if n not in FEATURE_RANGES]
    if missing:
        raise MissingFeatureRangeError(
            f"Booster declares {len(missing)} feature(s) without a FEATURE_RANGES entry: "
            f"{missing}. Add a FEATURE_RANGES entry (dtype-kind + value range) for each "
            "before deploying this model."
        )


def _check_columns(df: pd.DataFrame, feature_names: tuple[str, ...]) -> None:
    """Hard check on column set + order. Order matters for DMatrix construction."""
    expected = list(feature_names)
    actual_features = [c for c in df.columns if c not in ID_COLUMNS]

    missing = set(expected) - set(actual_features)
    extra = set(actual_features) - set(expected)
    if missing or extra:
        raise FeatureValidationError(
            f"Feature column set mismatch: missing={sorted(missing)}, extra={sorted(extra)}. "
            f"Expected (in order): {expected}. Actual (in order): {actual_features}."
        )

    if actual_features != expected:
        raise FeatureValidationError(f"Feature column order mismatch. Expected: {expected}. Actual: {actual_features}.")


def _check_dtype(name: str, series: pd.Series, allowed_kinds: str) -> None:
    """Validate a column's dtype.kind matches one of `allowed_kinds`."""
    kind = series.dtype.kind
    if kind not in allowed_kinds:
        raise FeatureValidationError(
            f"Feature {name!r} has dtype {series.dtype} (kind={kind!r}); expected one of kinds {list(allowed_kinds)!r}."
        )


def validate_features(df: pd.DataFrame, *, feature_names: tuple[str, ...]) -> None:
    """Hard-fail if `df` doesn't match the trained model's expected schema.

    Column set/order and dtype mismatches can only come from the SQL drifting
    away from the booster — never from row data — so they abort the chunk.
    Value-level violations are data-driven; flag those per-row with
    `out_of_contract_row_mask` instead.

    `feature_names` must be the booster's `feature_names` (production callers
    get this via `scorer.get_feature_names()`). Pure function; no global state.

    Raises:
        FeatureValidationError: any column or dtype mismatch.
    """
    if df.empty:
        return

    _check_columns(df, feature_names)
    for name in feature_names:
        series: pd.Series = df.loc[:, name]
        spec = FEATURE_RANGES[name]
        _check_dtype(name, series, spec.dtype_kind)


def out_of_contract_row_mask(df: pd.DataFrame, *, feature_names: tuple[str, ...]) -> pd.Series:
    """Boolean mask of rows whose feature values break the trained contract.

    Flags +/-inf (a feature-engineering bug — division returning inf) and
    values outside `FEATURE_RANGES` bounds. NaN passes — XGBoost handles it
    natively, and our SQL deliberately produces NULL (→ NaN) when
    denominators are zero.

    Replay events are client-controlled, so a single crafted session can
    produce an out-of-range derived feature. Flagging per-row lets callers
    drop just the offending sessions instead of failing the whole chunk
    (which would deterministically re-fail the same hash bucket every tick
    until the bad session ages past the lookback window).

    O(rows × features). On a 10k-row chunk × 61 features this is single-digit ms.
    """
    mask = pd.Series(False, index=df.index)
    for name in feature_names:
        series: pd.Series = df.loc[:, name]
        spec = FEATURE_RANGES[name]
        if series.dtype.kind == "f":
            arr = series.to_numpy()
            mask |= ~(np.isfinite(arr) | np.isnan(arr))
        if spec.min_value is not None:
            mask |= series.lt(spec.min_value).fillna(False)
        if spec.max_value is not None:
            mask |= series.gt(spec.max_value).fillna(False)
    return mask


def feature_matrix(df: pd.DataFrame, *, feature_names: tuple[str, ...]) -> pd.DataFrame:
    """Strip ID columns; return a DataFrame with feature columns in trained order.

    Preserves row order so callers can re-attach scores positionally.
    """
    return df.loc[:, list(feature_names)]
