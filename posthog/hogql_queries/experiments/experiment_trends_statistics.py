from scipy import stats
from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

from ee.clickhouse.queries.experiments import (
    FF_DISTRIBUTION_THRESHOLD,
)

Probability = float


def posterior_poisson(total_counts, total_exposures, alpha, beta):
    """Calculates the posterior distribution of a Poisson distribution given the data and prior parameters.

    Parameters
    ----------

    total_counts: int
      The total number of observed counts
    total_exposures: int
      The total number of exposed users
    alpha: float
      The prior hyper-parameters
    beta: float
      The prior hyper-parameter
    """
    prior = stats.gamma(a=alpha, scale=1 / beta)
    alpha = alpha + total_counts
    beta = beta + total_exposures
    posterior = stats.gamma(a=alpha, scale=1 / beta)

    return prior, posterior


def calculate_probabilities(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    simulations: int = 100_000,
) -> list[Probability]:
    """
    Calculates probability that each variant is the best using Bayesian inference.
    Uses a Poisson likelihood with Gamma prior for modeling count data.
    """
    if not control_variant:
        raise ValueError("No control variant data found")

    if len(test_variants) >= 10:
        raise ValueError("Can't calculate experiment results for more than 10 variants")

    if len(test_variants) < 1:
        raise ValueError("Can't calculate experiment results for less than 2 variants")

    variants = [control_variant, *test_variants]
    probabilities = []

    # For each variant, calculate probability it's the best
    for target_variant in variants:
        other_variants = [v for v in variants if v != target_variant]

        # Get posterior distribution for target variant
        _, target_posterior = posterior_poisson(
            target_variant.count,
            target_variant.exposure,
            alpha=1,  # prior alpha
            beta=1,  # prior beta
        )

        # Get posterior distributions for other variants
        other_posteriors = [
            posterior_poisson(
                variant.count,
                variant.exposure,
                alpha=1,  # prior alpha
                beta=1,  # prior beta
            )[1]
            for variant in other_variants
        ]

        # Sample from posteriors
        target_samples = target_posterior.rvs(simulations)
        other_samples = [p.rvs(simulations) for p in other_posteriors]

        # Count how often target variant is best
        wins = sum(
            target_sample > max(other_variant_samples)
            for target_sample, other_variant_samples in zip(target_samples, zip(*other_samples))
        )

        probabilities.append(wins / simulations)

    return probabilities


def are_results_significant(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[Probability],
    threshold: float = 0.95,
) -> tuple[ExperimentSignificanceCode, float]:
    """
    Determines if results are significant using Bayesian criteria:
    1. Check if we have enough exposure
    2. Check if any variant has high probability of being best
    """
    # Check minimum exposure
    if control_variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 0.0

    for variant in test_variants:
        if variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
            return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 0.0

    # Check if any variant has high probability of being best
    max_prob = max(probabilities)
    if max_prob > threshold:
        return ExperimentSignificanceCode.SIGNIFICANT, max_prob

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, max_prob


def calculate_credible_intervals(variants: list[ExperimentVariantTrendsBaseStats], interval: float = 0.95) -> dict:
    """
    Calculate credible intervals for each variant's rate parameter
    using the Gamma posterior distribution.
    """
    alpha = (1 - interval) / 2
    intervals = {}

    for variant in variants:
        posterior = stats.gamma(a=variant.count + 1, scale=1 / variant.exposure)

        lower, upper = posterior.ppf([alpha, 1 - alpha])
        intervals[variant.key] = (lower, upper)

    return intervals
