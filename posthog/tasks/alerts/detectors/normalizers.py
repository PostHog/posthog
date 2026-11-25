"""Map the raw scores of a detector to the 0 to 1 score that its threshold reads.

A detector returns a raw score per point, where a higher value is more unusual. A normalizer fits on the raw
scores of the training points and maps a new raw score to 0 to 1. The method is an internal config key
(`normalizer`) and not a field of the public detector schema, so users get one meaning for the score.
"""

import math
from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from scipy.special import erf

QUANTILE = "quantile"
MINMAX = "minmax"
MINMAX_STEP = "minmax_step"
UNIFY = "unify"

# `k` of the minimum training size `n >= k / (1 - threshold)`: the training points expected above the threshold.
# At 1, the threshold is the least it can be and still differ from "above every training point".
QUANTILE_POINTS_ABOVE_THRESHOLD = 1


class FitError(ValueError):
    """The history cannot fit this detector, for example because it is too short."""


class Normalizer(ABC):
    name: str

    def min_training_scores(self, threshold: float) -> int:
        """The fewest raw training scores that a fit accepts at this threshold."""
        return 1

    def fit(self, raw_scores: np.ndarray, threshold: float) -> dict[str, Any]:
        """JSON-safe parameters for ``score``. Raises ``FitError`` when the raw scores are too few."""
        raw_scores = np.asarray(raw_scores, dtype=float).ravel()
        minimum = self.min_training_scores(threshold)
        if len(raw_scores) < minimum:
            raise FitError(f"{len(raw_scores)} training scores cannot fit {self.name}, {minimum} needed")
        return self._fit(raw_scores)

    @abstractmethod
    def _fit(self, raw_scores: np.ndarray) -> dict[str, Any]: ...

    @abstractmethod
    def score(self, params: dict[str, Any], raw_score: float) -> float: ...


_NORMALIZERS: dict[str, Normalizer] = {}


def register_normalizer(cls: type[Normalizer]) -> type[Normalizer]:
    _NORMALIZERS[cls.name] = cls()
    return cls


def get_normalizer(name: str) -> Normalizer:
    if name not in _NORMALIZERS:
        raise ValueError(f"Unknown normalizer: {name}. Available: {sorted(_NORMALIZERS)}")
    return _NORMALIZERS[name]


def min_quantile_training_scores(threshold: float, k: int = QUANTILE_POINTS_ABOVE_THRESHOLD) -> int:
    """The fewest training scores for which a quantile ``threshold`` is not just "above every training point"."""
    if threshold >= 1:
        # No score is above 1, so this threshold never flags, whatever the training size.
        return 1
    # Rounding first keeps float error from adding a point, because 1 / (1 - 0.99) is 100.00000000000009.
    return max(math.ceil(round(k / (1 - max(threshold, 0.0)), 9)), 1)


@register_normalizer
class QuantileNormalizer(Normalizer):
    """The fraction of training raw scores that are strictly below the raw score.

    A point that only ties the largest training score stays below 1.0, and only a point above every training
    score reaches 1.0. A threshold of 0.99 then flags about the strangest 1% of points.
    """

    name = QUANTILE

    def min_training_scores(self, threshold: float) -> int:
        return min_quantile_training_scores(threshold)

    def _fit(self, raw_scores: np.ndarray) -> dict[str, Any]:
        return {"sorted_scores": [float(score) for score in np.sort(raw_scores)]}

    def score(self, params: dict[str, Any], raw_score: float) -> float:
        sorted_scores = params["sorted_scores"]
        return float(np.searchsorted(sorted_scores, raw_score, side="left") / len(sorted_scores))


@register_normalizer
class MinMaxNormalizer(Normalizer):
    """Min-max against the training raw scores, as PyOD's ``predict_proba`` with the ``linear`` method.

    Like scikit-learn's ``MinMaxScaler``, a range below ten machine epsilons keeps a scale of one, so the scores
    only shift. Training scores that differ only by float error then do not stretch a tiny difference to 1.0.
    """

    name = MINMAX

    def _fit(self, raw_scores: np.ndarray) -> dict[str, Any]:
        return {"min": float(raw_scores.min()), "max": float(raw_scores.max())}

    def score(self, params: dict[str, Any], raw_score: float) -> float:
        score_range = params["max"] - params["min"]
        if score_range < 10 * np.finfo(float).eps:
            score_range = 1.0
        return float(np.clip((raw_score - params["min"]) / score_range, 0.0, 1.0))


@register_normalizer
class MinMaxStepNormalizer(MinMaxNormalizer):
    """Min-max against the training raw scores, where a zero range gives 1.0 above the maximum and 0.0 otherwise."""

    name = MINMAX_STEP

    def score(self, params: dict[str, Any], raw_score: float) -> float:
        if params["max"] == params["min"]:
            return 1.0 if raw_score > params["max"] else 0.0
        return float(np.clip((raw_score - params["min"]) / (params["max"] - params["min"]), 0.0, 1.0))


@register_normalizer
class UnifyNormalizer(Normalizer):
    """Standardize against the training raw scores, then ``erf``, as PyOD's ``unify`` method."""

    name = UNIFY

    def _fit(self, raw_scores: np.ndarray) -> dict[str, Any]:
        return {"mean": float(raw_scores.mean()), "std": float(raw_scores.std())}

    def score(self, params: dict[str, Any], raw_score: float) -> float:
        if params["std"] == 0:
            return 1.0 if raw_score > params["mean"] else 0.0
        standardized = (raw_score - params["mean"]) / params["std"]
        return float(np.clip(erf(standardized / np.sqrt(2)), 0.0, 1.0))
