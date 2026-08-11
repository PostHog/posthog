import numpy as np
from parameterized import parameterized

from products.apm.backend.logic.anomaly_detection.bands import (
    IQRBandModel,
    MADBandModel,
    NegativeBinomialBandModel,
    PoissonBandModel,
    ZScoreBandModel,
    widen,
)
from products.apm.backend.logic.anomaly_detection.types import Band

ALPHA = 0.05 / 288


def make_rng() -> np.random.Generator:
    return np.random.default_rng(42)


class TestCountBands:
    def test_poisson_band_matches_theoretical_quantiles(self) -> None:
        samples = np.full(40, 100.0)
        band = PoissonBandModel().compute(samples, 100.0, 0.025)
        assert band.lower == 81.0
        assert band.upper == 120.0

    def test_poisson_lower_band_never_negative_at_low_rate(self) -> None:
        samples = np.full(40, 5.0)
        band = PoissonBandModel().compute(samples, 5.0, ALPHA)
        assert band.lower >= 0.0
        assert band.upper > 5.0

    def test_zscore_lower_band_goes_negative_at_low_rate(self) -> None:
        samples = make_rng().poisson(5.0, size=40).astype(float)
        band = ZScoreBandModel().compute(samples, 5.0, ALPHA)
        assert band.lower < 0.0

    def test_negative_binomial_inflates_band_for_overdispersed_samples(self) -> None:
        mu = 50.0
        overdispersed = make_rng().negative_binomial(2, 2 / (2 + mu), size=200).astype(float)
        nb_band = NegativeBinomialBandModel().compute(overdispersed, mu, ALPHA)
        poisson_band = PoissonBandModel().compute(overdispersed, mu, ALPHA)
        assert nb_band.upper > poisson_band.upper
        assert nb_band.lower <= poisson_band.lower

    def test_negative_binomial_falls_back_to_poisson_when_not_overdispersed(self) -> None:
        samples = np.full(40, 100.0)
        nb_band = NegativeBinomialBandModel().compute(samples, 100.0, ALPHA)
        poisson_band = PoissonBandModel().compute(samples, 100.0, ALPHA)
        assert nb_band.lower == poisson_band.lower
        assert nb_band.upper == poisson_band.upper

    def test_flat_baseline_still_produces_nonzero_width_band(self) -> None:
        samples = np.full(40, 20.0)
        band = NegativeBinomialBandModel().compute(samples, 20.0, ALPHA)
        assert band.upper > band.lower

    def test_rate_floor_prevents_spike_on_first_log_after_quiet(self) -> None:
        samples = np.zeros(40)
        band = PoissonBandModel(rate_floor=1.0).compute(samples, 1.0, ALPHA)
        assert band.upper >= 1.0


class TestRegistryBands:
    @parameterized.expand([(MADBandModel,), (ZScoreBandModel,), (IQRBandModel,)])
    def test_outlier_lands_above_band(self, model_cls: type) -> None:
        samples = make_rng().normal(100.0, 10.0, size=60).round()
        band = model_cls().compute(samples, 500.0, ALPHA)
        assert 500.0 > band.upper
        assert band.lower < 100.0 < band.upper


class TestWiden:
    def test_widen_scales_half_widths_around_expected(self) -> None:
        band = widen(Band(lower=80.0, upper=120.0, expected=100.0), 2.0)
        assert band.lower == 60.0
        assert band.upper == 140.0

    def test_widen_clamps_lower_at_zero(self) -> None:
        band = widen(Band(lower=2.0, upper=20.0, expected=10.0), 3.0)
        assert band.lower == 0.0

    def test_widen_factor_one_is_identity(self) -> None:
        band = Band(lower=80.0, upper=120.0, expected=100.0)
        assert widen(band, 1.0) is band
