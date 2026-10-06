"""The `model_explanation` shape the model card reads, and the reader for rows written before it existed."""

import math
from typing import Any

from django.db import models

MAX_TOP_FEATURES = 30


class FeatureDirection(models.TextChoices):
    POSITIVE = "positive"
    NEGATIVE = "negative"


# Champions written before the serializer was typed store their list under other keys.
_LEGACY_LIST_KEYS = ("top_features", "features", "feature_importances")
_LEGACY_IMPORTANCE_KEYS = ("importance", "auc_drop_when_shuffled", "gain")
_POSITIVE_WORDS = {"positive", "+", "up", "raises", "increases"}
_NEGATIVE_WORDS = {"negative", "-", "down", "lowers", "decreases"}


def _direction(value: Any) -> FeatureDirection | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text in _POSITIVE_WORDS:
        return FeatureDirection.POSITIVE
    if text in _NEGATIVE_WORDS:
        return FeatureDirection.NEGATIVE
    # Prose such as "higher -> less likely" or "lower = more likely".
    if "more likely" in text:
        positive = True
    elif "less likely" in text:
        positive = False
    else:
        return None
    if text.startswith("lower"):
        positive = not positive
    return FeatureDirection.POSITIVE if positive else FeatureDirection.NEGATIVE


def _feature(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name", raw.get("feature"))
    importance = next((raw[key] for key in _LEGACY_IMPORTANCE_KEYS if key in raw), None)
    direction = _direction(raw.get("direction"))
    if not isinstance(name, str) or not name or direction is None:
        return None
    if isinstance(importance, bool) or not isinstance(importance, int | float) or not math.isfinite(importance):
        return None
    return {"name": name, "importance": abs(float(importance)), "direction": direction.value}


def normalize_model_explanation(raw: Any) -> dict[str, Any]:
    """Map a stored explanation to `{top_features, method?, note?}` and drop entries it cannot read."""
    if not isinstance(raw, dict):
        return {"top_features": []}
    items: Any = next((raw[key] for key in _LEGACY_LIST_KEYS if isinstance(raw.get(key), list)), [])
    features = [f for f in (_feature(item) for item in items) if f is not None]
    features.sort(key=lambda f: f["importance"], reverse=True)
    result: dict[str, Any] = {"top_features": features[:MAX_TOP_FEATURES]}
    for key in ("method", "note"):
        if isinstance(raw.get(key), str) and raw[key]:
            result[key] = raw[key]
    return result
