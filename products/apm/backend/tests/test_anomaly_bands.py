import numpy as np
from parameterized import parameterized
from scipy import stats

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

    @parameterized.expand([(2.0,), (4.0,)])
    def test_negative_binomial_inflates_band_for_overdispersed_samples(self, shape: float) -> None:
        mu = 50.0
        probability = shape / (shape + mu)
        overdispersed = make_rng().negative_binomial(shape, probability, size=200).astype(float)
        nb_band = NegativeBinomialBandModel().compute(overdispersed, mu, ALPHA)
        poisson_band = PoissonBandModel().compute(overdispersed, mu, ALPHA)
        assert nb_band.upper > poisson_band.upper
        assert nb_band.lower <= poisson_band.lower
        false_positive_probability = stats.nbinom.cdf(nb_band.lower - 1, shape, probability) + stats.nbinom.sf(
            nb_band.upper, shape, probability
        )
        assert false_positive_probability < 0.005

    def test_negative_binomial_falls_back_to_poisson_when_not_overdispersed(self) -> None:
        samples = np.full(40, 100.0)
        nb_band = NegativeBinomialBandModel().compute(samples, 100.0, ALPHA)
        poisson_band = PoissonBandModel().compute(samples, 100.0, ALPHA)
        assert nb_band.lower == poisson_band.lower
        assert nb_band.upper == poisson_band.upper

    @parameterized.expand([(6,), (9,), (15,)])
    def test_negative_binomial_one_outlier_does_not_collapse_the_band(self, sample_count: int) -> None:
        samples = np.append(np.full(sample_count - 1, 10.0), 10000.0)
        band = NegativeBinomialBandModel().compute(samples, 10.0, ALPHA)
        assert band.lower < 10.0 < band.upper
        assert band.expected == 10.0
        assert band.upper < 30.0

    def test_batched_negative_binomial_bands_match_individual_bands(self) -> None:
        samples = [
            np.zeros(6),
            np.full(9, 100.0),
            np.append(np.full(5, 10.0), 10000.0),
            make_rng().negative_binomial(2, 0.04, size=40).astype(float),
        ]
        model = NegativeBinomialBandModel(rate_floor=12.0)
        assert model.compute_many(samples, ALPHA) == [model.compute(sample, 0.0, ALPHA) for sample in samples]
        assert model.compute_many([], ALPHA) == []

    def test_intermittent_baseline_keeps_robust_silence_expectation(self) -> None:
        samples = np.concatenate((np.zeros(90), np.full(10, 100.0)))
        model = NegativeBinomialBandModel()
        band = model.compute(samples, 0.0, ALPHA)
        assert band.expected == 0.0
        assert band.lower == 0.0
        assert band.upper > 100.0
        assert model.compute_many([samples], ALPHA) == [band]

    def test_overdispersed_baseline_keeps_its_upper_tail(self) -> None:
        samples = np.array([5.0, 10.0, 20.0, 40.0, 80.0, 1000.0])
        mean = float(np.mean(samples))
        variance = float(np.var(samples, ddof=1))
        shape = mean**2 / (variance - mean)
        probability = shape / (shape + mean)
        band = NegativeBinomialBandModel().compute(samples, 100.0, ALPHA)
        assert band.upper == stats.nbinom.ppf(1.0 - ALPHA, shape, probability)
        assert band.expected == mean

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
