import numpy as np
from rest_framework.exceptions import ValidationError
from scipy.stats import gamma

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.experiments import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

Probability = float

# Prior parameters (minimal prior knowledge)
ALPHA_0 = 1
BETA_0 = 1
SAMPLE_SIZE = 10000


def calculate_probabilities_v2_count(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Calculate the win probabilities for each variant in an experiment using Bayesian analysis.

    This function computes the probability that each variant is the best (i.e., has the highest
    rate) compared to all other variants, including the control. It uses a Gamma-Poisson model
    where samples are drawn from the posterior Gamma distributions of each variant's rate.

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, including count (events) and absolute_exposure
    test_variants : list[ExperimentVariantTrendsBaseStats]
        List of statistics for test variants to compare against the control

    Returns:
    --------
    list[float]
        A list of probabilities where each element represents:
        - index 0: probability control variant beats the best test variant
        - index i>0: probability test variant i-1 beats control

    Notes:
    ------
    - Uses a Bayesian approach with a Gamma distribution as the posterior
    - Assumes a minimally informative Gamma prior (alpha=1, beta=1)
    - Draws samples from the posterior to estimate win probabilities
    - Suitable for count/rate data following a Poisson distribution

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantTrendsBaseStats
    >>> from posthog.hogql_queries.experiments.trends_statistics_v2_count import calculate_probabilities_v2_count
    >>> control = ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1, absolute_exposure=1000)
    >>> test = ExperimentVariantTrendsBaseStats(key="test", count=120, exposure=1, absolute_exposure=1000)
    >>> calculate_probabilities_v2_count(control, [test])
    >>> # Returns: [0.088, 0.920] indicating the test variant is more likely to be the best
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    # Calculate posterior parameters for control
    alpha_control = ALPHA_0 + control_variant.count
    beta_control = BETA_0 + control_variant.absolute_exposure

    # Draw samples from control posterior
    samples_control = gamma.rvs(alpha_control, scale=1 / beta_control, size=SAMPLE_SIZE)

    # Draw samples for each test variant
    test_samples = []
    for test in test_variants:
        alpha_test = ALPHA_0 + test.count
        beta_test = BETA_0 + test.absolute_exposure
        test_samples.append(gamma.rvs(alpha_test, scale=1 / beta_test, size=SAMPLE_SIZE))

    # Calculate probabilities
    probabilities = []

    # Probability control wins (beats the best test variant)
    best_test_samples = np.max(test_samples, axis=0)
    control_wins = samples_control > best_test_samples
    probabilities.append(float(np.mean(control_wins)))

    # Probability each test variant wins (beats control only)
    for test_sample in test_samples:
        variant_wins = test_sample > samples_control
        probabilities.append(float(np.mean(variant_wins)))

    return probabilities


def are_results_significant_v2_count(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[Probability],
) -> tuple[ExperimentSignificanceCode, Probability]:
    """
    Determines if experiment results are statistically significant.

    This function evaluates whether any variant can be confidently declared as best by:
    1. Checking if variants have sufficient exposure (minimum threshold)
    2. Evaluating if the highest win probability exceeds the significance threshold
    3. For the variant with highest rate, calculating expected loss compared to alternatives

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, including count and absolute_exposure
    test_variants : list[ExperimentVariantTrendsBaseStats]
        List of statistics for test variants to compare against control
    probabilities : list[Probability]
        Win probabilities for each variant (must sum to 1), as calculated by calculate_probabilities_v2_count

    Returns:
    --------
    tuple[ExperimentSignificanceCode, Probability]
        - ExperimentSignificanceCode indicating result status:
          * NOT_ENOUGH_EXPOSURE: if any variant has exposure below threshold
          * LOW_WIN_PROBABILITY: if no variant exceeds probability threshold
          * HIGH_LOSS: if expected loss is too high for best variant
          * SIGNIFICANT: if a variant is confidently best
        - Expected loss value (between 0 and 1) for significant results, 1.0 for non-significant results

    Notes:
    ------
    - Uses FF_DISTRIBUTION_THRESHOLD for minimum exposure check
    - Uses MIN_PROBABILITY_FOR_SIGNIFICANCE (default 0.9) for win probability threshold
    - Uses EXPECTED_LOSS_SIGNIFICANCE_LEVEL for maximum acceptable expected loss
    - Expected loss represents the expected rate difference between chosen variant and potential better alternatives
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
    if max_probability >= MIN_PROBABILITY_FOR_SIGNIFICANCE:
        # Find best performing variant
        all_variants = [control_variant, *test_variants]
        rates = [v.count / v.absolute_exposure for v in all_variants]
        best_idx = np.argmax(rates)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]

        expected_loss = calculate_expected_loss_v2_count(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2_count(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate Bayesian credible intervals for each variant's rate using a Gamma-Poisson model.

    Credible intervals represent the range where we believe the true rate lies
    with a specified probability (default 95%). These intervals have a direct probabilistic
    interpretation: "There is a 95% probability that the true rate lies within this interval."

    Parameters:
    -----------
    variants : list[ExperimentVariantTrendsBaseStats]
        List of variants containing count (number of events) and absolute_exposure data
    lower_bound : float, optional (default=0.025)
        Lower percentile for the credible interval (2.5% for 95% CI)
    upper_bound : float, optional (default=0.975)
        Upper percentile for the credible interval (97.5% for 95% CI)

    Returns:
    --------
    dict[str, tuple[float, float]]
        Dictionary mapping variant keys to their credible intervals
        Each interval is a tuple of (lower_bound, upper_bound) representing rates

    Notes:
    ------
    - Uses a Gamma distribution as the posterior for the rate parameter
    - Assumes a minimally informative Gamma prior (alpha=1, beta=1)
    - Suitable for count/rate data following a Poisson distribution
    - Returns empty dict if any calculations fail
    - Intervals represent rates (events per exposure)

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantTrendsBaseStats
    >>> from posthog.hogql_queries.experiments.trends_statistics_v2_count import calculate_credible_intervals_v2_count
    >>> variants = [
    ...     ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1, absolute_exposure=1000),
    ...     ExperimentVariantTrendsBaseStats(key="test", count=150, exposure=1, absolute_exposure=1000)
    ... ]
    >>> calculate_credible_intervals_v2_count(variants)
    >>> # Returns: {"control": (0.082, 0.122), "test": (0.128, 0.176)}
    """
    intervals = {}

    for variant in variants:
        try:
            # Calculate posterior parameters using absolute_exposure
            alpha_posterior = ALPHA_0 + variant.count
            beta_posterior = BETA_0 + variant.absolute_exposure

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


def calculate_expected_loss_v2_count(
    target_variant: ExperimentVariantTrendsBaseStats, variants: list[ExperimentVariantTrendsBaseStats]
) -> float:
    """
    Calculates expected loss in count/rate using Gamma-Poisson conjugate prior.

    This implementation uses a Bayesian approach with Gamma-Poisson model to estimate
    the expected loss when choosing the target variant over others. The Gamma-Poisson
    model is used because:
    1. Count data follows a Poisson distribution (discrete events over time/exposure)
    2. The Gamma distribution is the conjugate prior for the Poisson rate parameter
    3. This combination allows for analytical posterior updates and handles rate uncertainty

    The model assumes:
    - Events occur independently at a constant rate
    - The number of events in any interval follows a Poisson distribution
    - The rate parameter has a Gamma prior distribution
    - The posterior distribution of the rate is also Gamma

    Parameters:
    -----------
    target_variant : ExperimentVariantTrendsBaseStats
        The variant being evaluated for loss, containing count and exposure data
    variants : list[ExperimentVariantTrendsBaseStats]
        List of other variants to compare against

    Returns:
    --------
    float
        Expected loss in rate if choosing the target variant. This represents
        the expected difference in rate between the target variant and the best
        performing alternative.

    Notes:
    ------
    - Uses minimally informative prior: Gamma(1,1)
    - Posterior parameters: alpha = prior_alpha + count, beta = prior_beta + exposure
    - Samples are drawn from posterior distributions to estimate expected loss
    - Loss is calculated as max(0, best_alternative - target) for each sample
    """
    # Calculate posterior parameters for target variant
    target_alpha = ALPHA_0 + target_variant.count
    target_beta = BETA_0 + target_variant.absolute_exposure

    # Draw samples from target variant's Gamma posterior
    target_samples = gamma.rvs(target_alpha, scale=1 / target_beta, size=SAMPLE_SIZE)

    # Draw samples from each comparison variant's Gamma posterior
    variant_samples = []
    for variant in variants:
        alpha = ALPHA_0 + variant.count
        beta = BETA_0 + variant.absolute_exposure
        samples = gamma.rvs(alpha, scale=1 / beta, size=SAMPLE_SIZE)
        variant_samples.append(samples)

    # Calculate loss
    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss
