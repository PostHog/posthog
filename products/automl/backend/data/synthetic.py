"""Synthetic per-user feature data with a binary churn target for prototype testing."""

from __future__ import annotations

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

_COUNTRIES = ["US", "GB", "DE", "FR", "JP", "IN", "BR", "AU"]
_PLAN_TIERS = ["free", "growth", "scale"]
_PLAN_TIER_PROBS = [0.70, 0.22, 0.08]


def generate_synthetic_dataset(n_users: int = 5000, seed: int = 42) -> pl.DataFrame:
    """Per-user features modeled loosely on aggregated PostHog event/property data.

    Churn is a logistic function of recency, pageview volume, plan tier, and
    tenure — gives AutoGluon a learnable signal without being trivially separable.
    """
    logger.info("synthetic_generate_start", n_users=n_users, seed=seed)
    rng = np.random.default_rng(seed)

    pageviews = rng.poisson(lam=22.0, size=n_users).astype(np.int64)
    sessions = rng.poisson(lam=5.0, size=n_users).astype(np.int64)
    last_active_days = rng.exponential(scale=7.0, size=n_users)
    signup_age_days = rng.exponential(scale=180.0, size=n_users)
    country = rng.choice(_COUNTRIES, size=n_users)
    plan = rng.choice(_PLAN_TIERS, size=n_users, p=_PLAN_TIER_PROBS)
    feature_a_used = rng.binomial(n=1, p=0.40, size=n_users).astype(np.int64)
    feature_b_used = rng.binomial(n=1, p=0.18, size=n_users).astype(np.int64)

    free_mask = (plan == "free").astype(np.float64)
    logit = -2.0 + 0.12 * last_active_days - 0.04 * pageviews + 0.6 * free_mask - 0.001 * signup_age_days
    churn_prob = 1.0 / (1.0 + np.exp(-logit))
    churned = rng.binomial(n=1, p=churn_prob).astype(np.int64)

    churn_rate = float(churned.mean())
    logger.info("synthetic_generate_done", n_users=n_users, churn_rate=round(churn_rate, 3))
    return pl.DataFrame(
        {
            "user_id": np.arange(n_users, dtype=np.int64),
            "pageviews_last_7d": pageviews,
            "sessions_last_7d": sessions,
            "last_active_days_ago": np.round(last_active_days, 2),
            "signup_age_days": np.round(signup_age_days, 1),
            "country": country.tolist(),
            "plan_tier": plan.tolist(),
            "feature_a_used": feature_a_used,
            "feature_b_used": feature_b_used,
            "churned": churned,
        }
    )


def write_synthetic_parquet(path: str, *, n_users: int = 5000, seed: int = 42) -> None:
    """Write the synthetic dataset to parquet. Supports local paths and s3:// URLs."""
    df = generate_synthetic_dataset(n_users=n_users, seed=seed)
    is_s3 = path.startswith("s3://")
    logger.info("synthetic_write_start", path=path, rows=len(df), via_s3=is_s3)
    if is_s3:
        from products.automl.backend.data.loader import DataLoader

        with DataLoader() as loader:
            loader.write_parquet(df, path)
    else:
        df.write_parquet(path)
    logger.info("synthetic_write_done", path=path)
