#!/usr/bin/env python3
"""Write checked-in example sessions + golden scores for bundled model tests.

Regenerate after changing FEATURE_RANGES, fetch_features_sql(), or model.ubj:

    flox activate -- bash -c "uv run python bin/generate_surfacing_example_fixtures.py"
"""

from __future__ import annotations

import sys
import json
import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd
import xgboost as xgb

REPO_ROOT = Path(__file__).resolve().parents[1]
SWEEP_PKG = REPO_ROOT / "posthog/temporal/session_replay/surfacing_scoring_sweep"
FIXTURES_PATH = (
    REPO_ROOT / "posthog/temporal/tests/session_replay/surfacing_scoring_sweep/fixtures/example_sessions.json"
)
_PKG_PREFIX = "posthog.temporal.session_replay.surfacing_scoring_sweep"
_SCHEMA_VERSION = 2


def _load_module(name: str, filename: str):
    module_name = f"{_PKG_PREFIX}.{name}"
    spec = importlib.util.spec_from_file_location(module_name, SWEEP_PKG / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _zero_features(feature_names: tuple[str, ...]) -> dict[str, float]:
    return dict.fromkeys(feature_names, 0.0)


def _example_sessions(feature_names: tuple[str, ...]) -> list[dict[str, Any]]:
    """Deterministic, realistic-ish profiles — not random, stable across regenerations."""

    checkout = _zero_features(feature_names)
    checkout.update(
        {
            "event_rate": 8.33,
            "click_rate": 0.4,
            "keypress_rate": 2.67,
            "mouse_activity_rate": 6.67,
            "page_visit_rate": 0.17,
            "checkout_path_visit_share": 0.6,
            "cart_path_visit_share": 0.2,
            "unique_url_share": 0.8,
            "mouse_mean_x": 640.0,
            "mouse_mean_y": 360.0,
            "inter_action_gap_mean_ms": 850.0,
            "network_request_rate": 1.5,
            "network_failure_ratio": 0.05,
        }
    )

    rage = _zero_features(feature_names)
    rage.update(
        {
            "event_rate": 12.0,
            "click_rate": 1.2,
            "rage_click_rate": 0.8,
            "dead_click_rate": 0.5,
            "console_error_rate": 0.3,
            "console_error_after_click_rate": 0.25,
            "network_failed_request_rate": 0.4,
            "network_failure_ratio": 0.35,
            "network_4xx_ratio": 0.2,
            "network_5xx_ratio": 0.15,
            "backspace_ratio": 0.1,
            "long_idle_gap_share": 0.05,
            "max_idle_gap_ms": 4500.0,
        }
    )

    bounce = _zero_features(feature_names)
    bounce.update(
        {
            "event_rate": 0.5,
            "page_visit_rate": 0.03,
            "unique_url_share": 1.0,
            "page_revisit_share": 0.0,
            "mouse_activity_rate": 0.1,
            "scroll_event_rate": 0.2,
            "max_idle_gap_ms": 120000.0,
        }
    )

    return [
        {
            "label": "high_engagement_checkout",
            "session_id": "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a1",
            "team_id": 1,
            "distinct_id": "user-checkout",
            "min_first_timestamp": "2026-05-07T10:00:00+00:00",
            "features": checkout,
        },
        {
            "label": "rage_click_with_errors",
            "session_id": "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a2",
            "team_id": 1,
            "distinct_id": "user-frustrated",
            "min_first_timestamp": "2026-05-07T11:30:00+00:00",
            "features": rage,
        },
        {
            "label": "quick_bounce",
            "session_id": "01939d3e-7c80-7b56-bf8d-1e74e5c3b3a3",
            "team_id": 2,
            "distinct_id": "user-bounce",
            "min_first_timestamp": "2026-05-07T12:15:00+00:00",
            "features": bounce,
        },
    ]


def _session_dataframe(session: dict[str, Any], feature_names: tuple[str, ...]) -> pd.DataFrame:
    row: dict[str, Any] = {
        "team_id": session["team_id"],
        "session_id": session["session_id"],
        "distinct_id": session["distinct_id"],
        "min_first_timestamp": pd.Timestamp(session["min_first_timestamp"]),
    }
    row.update(session["features"])
    return pd.DataFrame([row], columns=["team_id", "session_id", "distinct_id", "min_first_timestamp", *feature_names])


def main() -> None:
    features_mod = _load_module("features", "features.py")
    _load_module("sql", "sql.py")
    feature_schema_mod = _load_module("feature_schema", "feature_schema.py")
    scorer_mod = _load_module("scorer", "scorer.py")

    feature_names = tuple(features_mod.FEATURE_RANGES.keys())
    model_path = SWEEP_PKG / "model.ubj"
    booster = xgb.Booster()
    booster.load_model(str(model_path))
    booster_names = tuple(booster.feature_names or ())
    feature_schema_mod.assert_serving_schema_parity(booster_names)

    sessions = _example_sessions(feature_names)
    for session in sessions:
        df = _session_dataframe(session, feature_names)
        features_mod.validate_features(df, feature_names=booster_names)
        scores = scorer_mod.predict(df)
        score = float(scores[0])
        if not 0.0 <= score <= 1.0:
            raise RuntimeError(f"Score out of range for {session['label']}: {score}")
        session["expected_score"] = score

    payload = {
        "schema_version": _SCHEMA_VERSION,
        "model_feature_schema_version": features_mod.MODEL_FEATURE_SCHEMA_VERSION,
        "feature_count": len(feature_names),
        "sessions": sessions,
    }
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    sys.stdout.write(f"Wrote {FIXTURES_PATH} ({len(sessions)} sessions)\n")


if __name__ == "__main__":
    main()
