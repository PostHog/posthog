"""Shared helpers for anomaly detection activities."""

from __future__ import annotations

from typing import Any

import posthoganalytics
from dateutil.relativedelta import relativedelta

from posthog.schema import IntervalType, TrendsQuery

from posthog.models.insight import Insight
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.utils import NON_TIME_SERIES_DISPLAY_TYPES, WRAPPER_NODE_KINDS
from posthog.utils import get_from_dict_or_attr

FEATURE_FLAG_KEY = "anomalies-tab"

DEFAULT_PREPROCESSING = {"diffs_n": 1, "lags_n": 5}

DEFAULT_ANOMALY_DETECTOR_CONFIG: dict[str, Any] = {
    "type": "ensemble",
    "operator": "or",
    "threshold": 0.95,
    "detectors": [
        {"type": "zscore", "threshold": 0.95, "preprocessing": DEFAULT_PREPROCESSING},
        {
            "type": "knn",
            "threshold": 0.95,
            "n_neighbors": 5,
            "method": "largest",
            "preprocessing": DEFAULT_PREPROCESSING,
        },
        {
            "type": "isolation_forest",
            "threshold": 0.95,
            "n_estimators": 100,
            "preprocessing": DEFAULT_PREPROCESSING,
        },
    ],
}

SPARKLINE_POINTS: dict[str, int] = {
    "hour": 48,
    "day": 30,
    "week": 12,
    "month": 12,
}

# How many historical points to request when training a fresh model, per
# insight interval. Sized so each window captures enough seasonal context
# for the ensemble to learn a realistic baseline (e.g. a full day-of-week
# cycle on hourly, a full quarter of weekday / weekend rhythm on daily).
# The alerts system keeps its legacy `DETECTOR_DEFAULT_WINDOW = 30` — this
# override applies to the anomalies-tab training flow only.
TRAIN_WINDOW_TARGET: dict[str, int] = {
    "hour": 24 * 7 * 2,  # 2 weeks of hourly (336)
    "day": 90,  # ~3 months of daily
    "week": 52,  # 1 year of weekly
    "month": 24,  # 2 years of monthly
}

# Minimum number of points required before we'll attempt to train. A series
# with fewer points than this is skipped — the detector output would be too
# noisy to trust, and the next training run has a chance to pick it up once
# more history accrues.
MIN_TRAIN_POINTS: dict[str, int] = {
    "hour": 48,  # at least 2 days
    "day": 14,  # at least 2 weeks
    "week": 8,  # at least 2 months
    "month": 6,  # at least 6 months
}

INTERVAL_DELTA: dict[str, relativedelta] = {
    "hour": relativedelta(hours=1),
    "day": relativedelta(days=1),
    "week": relativedelta(weeks=1),
    "month": relativedelta(months=1),
}

# How often to retrain models per insight interval
RETRAIN_CADENCE: dict[str, relativedelta] = {
    "hour": relativedelta(days=1),
    "day": relativedelta(weeks=1),
    "week": relativedelta(weeks=4),
    "month": relativedelta(months=3),
}


def tune_training_config_for_interval(detector_config: dict[str, Any], interval: str) -> dict[str, Any]:
    """Return a copy of `detector_config` with per-sub-detector `window` set
    to match the interval's `TRAIN_WINDOW_TARGET`.

    The alerts system's `_compute_min_samples_for_detector` resolves
    `min_samples = window + 1 + lags_n + diffs_n`, then
    `_date_range_override_for_detector` turns that into a `-{n}{unit}` query
    window. So by fitting `window` here we steer the CH query for training
    without touching either helper.

    Falls back silently to the original config when the interval isn't
    recognised, keeping behaviour identical for non-time-series inputs.
    """
    target = TRAIN_WINDOW_TARGET.get(interval)
    if target is None:
        return detector_config

    def _with_window(sub: dict[str, Any]) -> dict[str, Any]:
        preprocessing = sub.get("preprocessing") or {}
        lags_n = preprocessing.get("lags_n") or 0
        diffs_n = preprocessing.get("diffs_n") or 0
        # Subtract preprocessing overhead so the resolved `min_samples`
        # lands at `target`, not `target + headroom`.
        window = max(target - 1 - lags_n - diffs_n, 1)
        return {**sub, "window": window}

    tuned = {**detector_config}
    if detector_config.get("type") == "ensemble":
        tuned["detectors"] = [_with_window(s) for s in detector_config.get("detectors", [])]
    else:
        tuned = _with_window(detector_config)
    return tuned


def min_points_for_scoring(detector_config: dict[str, Any]) -> int:
    """Compute the minimum data points needed to score 1 new point.

    For scoring (not training), we only need enough points for preprocessing
    to produce 1 valid output. With diffs_n=1 and lags_n=5, preprocessing
    consumes 6 points, so we need 7 points total (6 consumed + 1 scored).

    We take the max across all sub-detectors in the ensemble.
    """
    sub_detectors = detector_config.get("detectors", [detector_config])
    max_needed = 2  # absolute minimum: 1 point + 1 for context

    for sub in sub_detectors:
        preprocessing = sub.get("preprocessing", {})
        diffs_n = preprocessing.get("diffs_n", 0)
        lags_n = preprocessing.get("lags_n", 0)
        # diffs consumes diffs_n points, lags consumes lags_n points
        # plus 1 for the actual point to score
        needed = 1 + diffs_n + lags_n
        max_needed = max(max_needed, needed)

    return max_needed


def interval_from_query(query: TrendsQuery) -> str:
    match query.interval:
        case IntervalType.HOUR:
            return "hour"
        case IntervalType.WEEK:
            return "week"
        case IntervalType.MONTH:
            return "month"
        case _:
            return "day"


def is_time_series_trends_insight(insight: Insight) -> tuple[bool, TrendsQuery | None]:
    """Check if an insight is a time-series TrendsQuery."""
    if insight.query is None:
        return False, None

    with upgrade_query(insight):
        query = insight.query

    kind = get_from_dict_or_attr(query, "kind")
    if kind in [k.value if hasattr(k, "value") else k for k in WRAPPER_NODE_KINDS]:
        query = get_from_dict_or_attr(query, "source")
        kind = get_from_dict_or_attr(query, "kind")

    if kind != "TrendsQuery":
        return False, None

    try:
        trends_query = TrendsQuery.model_validate(query)
    except Exception:
        return False, None

    display = trends_query.trendsFilter.display if trends_query.trendsFilter else None
    if display in NON_TIME_SERIES_DISPLAY_TYPES:
        return False, None

    return True, trends_query


def is_anomalies_enabled_for_team(team: Any) -> bool:
    from django.conf import settings

    if settings.DEBUG:
        return True

    return posthoganalytics.feature_enabled(
        FEATURE_FLAG_KEY,
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
