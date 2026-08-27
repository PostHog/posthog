"""Candidate band models for the bake-off.

All models share one decision semantics: given baseline samples and a per-side
alpha, produce a ``Band``; the detector flags observed counts outside the
(possibly widened) band. That keeps the comparison apples-to-apples — same
alpha budget, same widening — while the models differ in how they estimate
dispersion and shape:

* ``poisson`` / ``negative_binomial`` are new count-aware asymmetric bands.
  They are not in the alerts detector registry; the recorded reason for fresh
  code is that count-aware asymmetric bands are locked architecturally and no
  registry scorer models counts (symmetric bands go negative at low rates,
  making drops undetectable).
* ``mad`` / ``zscore`` / ``iqr`` reuse the alerts detector registry scorers:
  the registry detector is fitted on the baseline samples and the band is read
  off its fitted statistics at the equivalent normal quantile.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from scipy import stats

from products.apm.backend.logic.anomaly_detection.types import Band

TRIM_FRACTION = 0.1
# Modified z-score scale: MAD of a normal distribution is 0.6745 sigma.
MAD_TO_SIGMA = 0.6745
# Under normality, IQR = 1.349 sigma and Q1 sits at -0.674 sigma.
NORMAL_IQR_IN_SIGMA = 1.349
NORMAL_Q1_IN_SIGMA = 0.674
TUKEY_FENCE_K = 1.5
# Sample variance within this ratio of the mean counts as "not overdispersed".
OVERDISPERSION_TOLERANCE = 1.001


class BandModel(Protocol):
    name: str

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band: ...


def widen(band: Band, factor: float) -> Band:
    if factor == 1.0:
        return band
    lower = band.expected - (band.expected - band.lower) * factor
    upper = band.expected + (band.upper - band.expected) * factor
    return Band(lower=max(lower, 0.0), upper=upper, expected=band.expected)


def _robust_rate(samples: np.ndarray) -> float:
    return float(stats.trim_mean(samples, TRIM_FRACTION)) if samples.size >= 3 else float(np.mean(samples))


def _poisson_interval(mu: float, alpha: float) -> tuple[float, float]:
    return float(stats.poisson.ppf(alpha, mu)), float(stats.poisson.ppf(1.0 - alpha, mu))


class PoissonBandModel:
    name = "poisson"

    def __init__(self, rate_floor: float = 1.0) -> None:
        self.rate_floor = rate_floor

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band:
        mu = _robust_rate(samples)
        lower, upper = _poisson_interval(max(mu, self.rate_floor), alpha)
        return Band(lower=lower, upper=upper, expected=mu)


class NegativeBinomialBandModel:
    """Poisson band inflated to the measured sample dispersion.

    Falls back to the Poisson band when the samples are not overdispersed —
    Poisson is the tightest band a count series is allowed.
    """

    name = "negative_binomial"

    def __init__(self, rate_floor: float = 1.0, dispersion_floor: float = 1.0) -> None:
        self.rate_floor = rate_floor
        self.dispersion_floor = dispersion_floor

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band:
        mu = _robust_rate(samples)
        mu_eff = max(mu, self.rate_floor)
        var = float(np.var(samples, ddof=1)) if samples.size >= 2 else mu_eff
        var = max(var, mu_eff * self.dispersion_floor)
        if var <= mu_eff * OVERDISPERSION_TOLERANCE:
            lower, upper = _poisson_interval(mu_eff, alpha)
        else:
            r = mu_eff**2 / (var - mu_eff)
            p = r / (r + mu_eff)
            lower = float(stats.nbinom.ppf(alpha, r, p))
            upper = float(stats.nbinom.ppf(1.0 - alpha, r, p))
        return Band(lower=lower, upper=upper, expected=mu)


class _RegistryBandModel:
    """Base for models that reuse an alerts detector registry scorer."""

    name: str
    detector_type: str  # a posthog.schema.DetectorType value

    def _fit_metadata(self, samples: np.ndarray, observed: float) -> dict[str, float]:
        # noqa comment applies to the import chain, not laziness for its own
        # sake: posthog.tasks.__init__ imports Django models, so a module-level
        # import would make this whole package require django.setup() — the
        # detector must stay importable with no infra.
        from posthog.tasks.alerts.detectors.registry import get_detector  # noqa: PLC0415

        detector = get_detector({"type": self.detector_type, "window": int(samples.size)})
        result = detector.detect(np.append(samples.astype(float), observed))
        return result.metadata


class MADBandModel(_RegistryBandModel):
    name = "mad"
    detector_type = "mad"

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band:
        meta = self._fit_metadata(samples, observed)
        median = meta["median"]
        mad = meta["median_abs_deviation"]
        k = float(stats.norm.ppf(1.0 - alpha))
        half_width = k * mad / MAD_TO_SIGMA
        return Band(lower=median - half_width, upper=median + half_width, expected=median)


class ZScoreBandModel(_RegistryBandModel):
    name = "zscore"
    detector_type = "zscore"

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band:
        meta = self._fit_metadata(samples, observed)
        mean = meta["mean"]
        std = meta["std"]
        k = float(stats.norm.ppf(1.0 - alpha))
        return Band(lower=mean - k * std, upper=mean + k * std, expected=mean)


class IQRBandModel(_RegistryBandModel):
    name = "iqr"
    detector_type = "iqr"

    def compute(self, samples: np.ndarray, observed: float, alpha: float) -> Band:
        meta = self._fit_metadata(samples, observed)
        q1, q3, iqr = meta["q1"], meta["q3"], meta["iqr"]
        # Fence multiplier equivalent to the per-side alpha under normality,
        # floored at Tukey's conventional fence.
        k = max(
            (float(stats.norm.ppf(1.0 - alpha)) - NORMAL_Q1_IN_SIGMA) / NORMAL_IQR_IN_SIGMA,
            TUKEY_FENCE_K,
        )
        expected = (q1 + q3) / 2.0
        return Band(lower=q1 - k * iqr, upper=q3 + k * iqr, expected=expected)


def default_band_models(rate_floor: float = 1.0, dispersion_floor: float = 1.0) -> list[BandModel]:
    return [
        PoissonBandModel(rate_floor=rate_floor),
        NegativeBinomialBandModel(rate_floor=rate_floor, dispersion_floor=dispersion_floor),
        MADBandModel(),
        ZScoreBandModel(),
        IQRBandModel(),
    ]
