from rest_framework.exceptions import ValidationError
from sentry_sdk import capture_exception
from posthog.hogql_queries.experiments import FF_DISTRIBUTION_THRESHOLD, MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.hogql_queries.experiments.funnels_statistics import Probability
from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats
from scipy.stats import gamma
import numpy as np

# Prior parameters (minimal prior knowledge)
PRIOR_ALPHA = 1
PRIOR_BETA = 1

SAMPLE_SIZE = 10000


def calculate_probabilities_v2(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Calculate the win probabilities for each variant in an experiment using Bayesian analysis.

    This function computes the probability that each variant is the best (i.e., has the highest
    conversion rate) compared to all other variants, including the control. It uses samples
    drawn from the posterior distributions of each variant's conversion rate.

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, including count (successes) and exposure (total trials)
    test_variants : list[ExperimentVariantTrendsBaseStats]
        List of statistics for test variants to compare against the control

    Returns:
    --------
    list[float]
        A list of probabilities where:
        - The first element is the probability that the control variant is the best
        - Subsequent elements are the probabilities that each test variant is the best

    Notes:
    ------
    - Uses a Bayesian approach with a Beta distribution as the posterior
    - Assumes a minimally informative prior (alpha=1, beta=1)
    - Draws samples from the posterior to estimate win probabilities

    Example:
    --------
    >>> control = ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1000, absolute_exposure=1000)
    >>> test = ExperimentVariantTrendsBaseStats(key="test", count=120, exposure=1000, absolute_exposure=1000)
    >>> probabilities = calculate_probabilities_v2(control, [test])
    >>> # Returns: [0.085, 0.915] indicating the test variant is more likely to be the best
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    # Calculate posterior parameters for control
    alpha_control = PRIOR_ALPHA + control_variant.count
    beta_control = PRIOR_BETA + control_variant.exposure

    # Draw samples from control posterior
    samples_control = gamma.rvs(alpha_control, scale=1 / beta_control, size=SAMPLE_SIZE)

    # Draw samples for each test variant
    test_samples = []
    for test in test_variants:
        alpha_test = PRIOR_ALPHA + test.count
        beta_test = PRIOR_BETA + test.exposure
        test_samples.append(gamma.rvs(alpha_test, scale=1 / beta_test, size=SAMPLE_SIZE))

    # Calculate probabilities
    probabilities = []

    # Probability control wins (beats all test variants)
    control_wins = np.all([samples_control > test_sample for test_sample in test_samples], axis=0)
    probabilities.append(float(np.mean(control_wins)))

    # Probability each test variant wins (beats control and all other test variants)
    for i, test_sample in enumerate(test_samples):
        other_test_samples = test_samples[:i] + test_samples[i + 1 :]
        variant_wins = np.all(
            [test_sample > samples_control] + [test_sample > other for other in other_test_samples], axis=0
        )
        probabilities.append(float(np.mean(variant_wins)))

    return probabilities


def are_results_significant_v2(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[Probability],
) -> tuple[ExperimentSignificanceCode, Probability]:
    """
    Determines if experiment results are statistically significant using Bayesian analysis.

    This function evaluates the win probabilities of each variant to determine if any variant
    is significantly better than the others. The method:
    1. Checks if sample sizes meet minimum threshold requirements
    2. Evaluates win probabilities from the posterior distributions

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, including count and exposure data
    test_variants : list[ExperimentVariantTrendsBaseStats]
        List of statistics for test variants to compare against control
    probabilities : list[Probability]
        List of win probabilities for each variant, as calculated by calculate_probabilities

    Returns:
    --------
    tuple[ExperimentSignificanceCode, Probability]
        - ExperimentSignificanceCode indicating the significance status:
            NOT_ENOUGH_EXPOSURE: Insufficient sample size
            LOW_WIN_PROBABILITY: No variant has a high enough probability of being best
            SIGNIFICANT: Clear winner with high probability of being best
        - Probability value (1.0 for NOT_ENOUGH_EXPOSURE and LOW_WIN_PROBABILITY, 0.0 for SIGNIFICANT)

    Notes:
    ------
    - Uses a Bayesian approach to determine significance
    - Does not use credible interval comparisons
    - p_value is a placeholder (1.0 or 0.0) to indicate significance status
    """
    # Check exposure thresholds
    for variant in test_variants:
        if variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
            return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    if control_variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    # Find highest probability among all variants
    max_probability = max(probabilities)

    # Check if any variant has a high enough probability of being best
    if max_probability < MIN_PROBABILITY_FOR_SIGNIFICANCE:
        return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0

    return ExperimentSignificanceCode.SIGNIFICANT, 0.0


def calculate_credible_intervals_v2(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate Bayesian credible intervals for each variant's conversion rate.

    Credible intervals represent the range where we believe the true conversion rate lies
    with a specified probability (default 95%). Unlike frequentist confidence intervals,
    these have a direct probabilistic interpretation: "There is a 95% probability that
    the true conversion rate lies within this interval."

    Parameters:
    -----------
    variants : list[ExperimentVariantTrendsBaseStats]
        List of variants containing count (successes) and exposure (total trials) data
    lower_bound : float, optional (default=0.025)
        Lower percentile for the credible interval (2.5% for 95% CI)
    upper_bound : float, optional (default=0.975)
        Upper percentile for the credible interval (97.5% for 95% CI)

    Returns:
    --------
    dict[str, tuple[float, float]]
        Dictionary mapping variant keys to their credible intervals
        Each interval is a tuple of (lower_bound, upper_bound)

    Notes:
    ------
    - Uses a Gamma distribution as the posterior distribution
    - Assumes a minimally informative prior (alpha=1, beta=1)
    - Intervals are calculated for visualization purposes, not for significance testing
    - Returns empty dict if any calculations fail

    Example:
    --------
    >>> variants = [
    ...     ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1000, absolute_exposure=1000),
    ...     ExperimentVariantTrendsBaseStats(key="test", count=150, exposure=1000, absolute_exposure=1000)
    ... ]
    >>> intervals = calculate_credible_intervals_v2(variants)
    >>> # Returns: {"control": (0.082, 0.122), "test": (0.128, 0.176)}
    """
    intervals = {}

    for variant in variants:
        try:
            # Calculate posterior parameters using absolute_exposure
            alpha_posterior = PRIOR_ALPHA + variant.count
            beta_posterior = PRIOR_BETA + variant.absolute_exposure

            # Calculate credible intervals using the posterior distribution
            credible_interval = gamma.ppf([lower_bound, upper_bound], alpha_posterior, scale=1 / beta_posterior)

            intervals[variant.key] = (float(credible_interval[0]), float(credible_interval[1]))
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals
