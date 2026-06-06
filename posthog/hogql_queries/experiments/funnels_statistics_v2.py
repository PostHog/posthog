import numpy as np
from scipy import stats
from scipy.stats import betabinom

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantFunnelsBaseStats

from posthog.hogql_queries.experiments import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

ALPHA_PRIOR = 1
BETA_PRIOR = 1
SAMPLE_SIZE = 10000


def calculate_probabilities_v2(
    control: ExperimentVariantFunnelsBaseStats, variants: list[ExperimentVariantFunnelsBaseStats]
) -> list[float]:
    """
    Calculate the win probabilities for each variant in an experiment using Bayesian analysis
    for funnel conversion rates.

    This function computes the probability that each variant is the best (i.e., has the highest
    conversion rate) compared to all other variants, including the control. It uses a Beta
    distribution as the "conjugate prior" for binomial (success/failure) data, and starts with
    Beta(1,1) as a minimally informative prior distribution. The "conjugate prior" means that
    the prior and posterior distributions are the same family, and the posterior is easy
    to compute.

    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Statistics for the control group, containing success_count and failure_count
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of statistics for test variants to compare against the control

    Returns:
    --------
    list[float]
        A list of probabilities where each element represents:
        - index 0: probability control beats the best test variant
        - index i>0: probability test variant i-1 beats control

    Notes:
    ------
    - Uses a Bayesian approach with Beta distributions as conjugate prior for binomial data
    - Uses Beta(1,1) as minimally informative prior (uniform over [0,1])
    - Draws SAMPLE_SIZE (10,000) samples from each variant's posterior distribution
    - Calculates win probability as frequency of samples where variant is maximum

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantFunnelsBaseStats
    >>> from posthog.hogql_queries.experiments.funnels_statistics_v2 import calculate_probabilities_v2
    >>> control = ExperimentVariantFunnelsBaseStats(key="control", success_count=100, failure_count=900)
    >>> test = ExperimentVariantFunnelsBaseStats(key="test", success_count=150, failure_count=850)
    >>> calculate_probabilities_v2(control, [test])
    >>> # Returns: [0.001, 0.999] indicating the test variant is very likely to be best
    """
    all_variants = [control, *variants]

    # Use Beta distribution for conversion rates
    samples: list[np.ndarray] = []
    for variant in all_variants:
        # Add prior to both successes and failures for Bayesian prior
        alpha = ALPHA_PRIOR + variant.success_count
        beta = BETA_PRIOR + variant.failure_count
        # Generate samples from Beta distribution
        variant_samples = np.random.beta(alpha, beta, SAMPLE_SIZE)
        samples.append(variant_samples)

    samples_array = np.array(samples)
    probabilities = []
    control_samples = samples_array[0]  # Control is always first variant

    # Find the best test variant at each sample point
    test_variants_samples = samples_array[1:]
    best_variant_samples = np.max(test_variants_samples, axis=0)

    # Control's probability is of being better than the best test variant
    control_prob = np.mean(control_samples >= best_variant_samples)
    probabilities.append(float(control_prob))

    # For each test variant, calculate probability of beating control
    for i in range(1, len(all_variants)):
        probability = np.mean(samples_array[i] > control_samples)
        probabilities.append(float(probability))

    return probabilities


def calculate_expected_loss_v2(
    target_variant: ExperimentVariantFunnelsBaseStats, variants: list[ExperimentVariantFunnelsBaseStats]
) -> float:
    """
    Calculates expected loss in conversion rate using Beta-Binomial conjugate prior.

    This implementation uses a Bayesian approach with Beta-Binomial model
    to estimate the expected loss when choosing the target variant over others.

    Parameters:
    -----------
    target_variant : ExperimentVariantFunnelsBaseStats
        The variant being evaluated for loss
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of other variants to compare against

    Returns:
    --------
    float
        Expected loss in conversion rate if choosing the target variant
    """
    # Calculate posterior parameters for target variant
    target_alpha = int(ALPHA_PRIOR + target_variant.success_count)
    target_beta = int(BETA_PRIOR + target_variant.failure_count)
    target_n = int(target_variant.success_count + target_variant.failure_count)

    # Get samples from target variant's Beta-Binomial
    target_samples = betabinom.rvs(target_n, target_alpha, target_beta, size=SAMPLE_SIZE) / target_n

    # Get samples from each comparison variant
    variant_samples = []
    for variant in variants:
        n = int(variant.success_count + variant.failure_count)
        alpha = int(ALPHA_PRIOR + variant.success_count)
        beta = int(BETA_PRIOR + variant.failure_count)
        samples = betabinom.rvs(n, alpha, beta, size=SAMPLE_SIZE) / n
        variant_samples.append(samples)

    # Calculate loss
    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss


def are_results_significant_v2(
    control: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats],
    probabilities: list[float],
) -> tuple[ExperimentSignificanceCode, float]:
    """
    Determine if the experiment results are statistically significant using Bayesian analysis
    for funnel conversion rates.

    This function evaluates whether there is strong evidence that any variant is better
    than the others by considering both winning probabilities and expected loss. It checks
    if the sample size is sufficient and evaluates the risk of choosing the winning variant.

    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Statistics for the control group, including success and failure counts
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of statistics for test variants to compare against the control
    probabilities : list[float]
        List of probabilities from calculate_probabilities_v2

    Returns:
    --------
    tuple[ExperimentSignificanceCode, float]
        A tuple containing:
        - Significance code indicating the result (significant, not enough exposure, high loss, etc.)
        - Expected loss value for significant results, 1.0 for non-significant results

    Notes:
    ------
    - Requires minimum exposure threshold per variant for reliable results
    - Uses probability threshold from MIN_PROBABILITY_FOR_SIGNIFICANCE
    - Calculates expected loss for the best-performing variant
    - Returns HIGH_LOSS if expected loss exceeds significance threshold
    - Returns NOT_ENOUGH_EXPOSURE if sample size requirements not met
    """
    # Check minimum exposure
    if control.success_count + control.failure_count < FF_DISTRIBUTION_THRESHOLD or any(
        v.success_count + v.failure_count < FF_DISTRIBUTION_THRESHOLD for v in variants
    ):
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    # Check if any variant has high enough probability
    max_probability = max(probabilities)
    if max_probability >= MIN_PROBABILITY_FOR_SIGNIFICANCE:
        # Find best performing variant
        all_variants = [control, *variants]
        conversion_rates = [v.success_count / (v.success_count + v.failure_count) for v in all_variants]
        best_idx = np.argmax(conversion_rates)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]
        expected_loss = calculate_expected_loss_v2(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2(variants: list[ExperimentVariantFunnelsBaseStats]) -> dict[str, list[float]]:
    """
    Calculate Bayesian credible intervals for conversion rates of each variant.

    This function computes the 95% credible intervals for the true conversion rate
    of each variant using a Beta model. The interval represents the range where we
    believe the true conversion rate lies with 95% probability.

    Parameters:
    -----------
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of all variants (including control), each containing success_count and failure_count

    Returns:
    --------
    dict[str, list[float]]
        Dictionary mapping variant keys to [lower, upper] credible intervals, where:
        - lower is the 2.5th percentile of the Beta posterior distribution
        - upper is the 97.5th percentile of the Beta posterior distribution
        - intervals represent conversion rates between 0 and 1

    Notes:
    ------
    - Uses Beta distribution as conjugate prior for binomial data
    - Uses Beta(1,1) as minimally informative prior (uniform over [0,1])
    - Computes 95% credible intervals (2.5th to 97.5th percentiles)
    - Intervals become narrower with more data (larger success_count + failure_count)
    - Returns empty dict if any calculations fail

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantFunnelsBaseStats
    >>> from posthog.hogql_queries.experiments.funnels_statistics_v2 import calculate_credible_intervals_v2
    >>> variants = [
    ...     ExperimentVariantFunnelsBaseStats(key="control", success_count=100, failure_count=900),
    ...     ExperimentVariantFunnelsBaseStats(key="test", success_count=150, failure_count=850)
    ... ]
    >>> calculate_credible_intervals_v2(variants)
    >>> # Returns: {"control": [0.083, 0.120], "test": [0.129, 0.173]}
    """
    intervals = {}

    for variant in variants:
        # Add 1 to both successes and failures for Bayesian prior
        alpha = ALPHA_PRIOR + variant.success_count
        beta = BETA_PRIOR + variant.failure_count

        # Calculate 95% credible interval
        lower, upper = stats.beta.ppf([0.025, 0.975], alpha, beta)

        intervals[variant.key] = [float(lower), float(upper)]

    return intervals
