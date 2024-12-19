import numpy as np
from scipy import stats
from posthog.schema import ExperimentVariantFunnelsBaseStats, ExperimentSignificanceCode
from posthog.hogql_queries.experiments import (
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
)
from scipy.stats import betabinom

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
    conversion rate) compared to all other variants, including the control. It uses samples
    drawn from the posterior Beta distributions of each variant's conversion rate.

    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Statistics for the control group, including success and failure counts
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of statistics for test variants to compare against the control

    Returns:
    --------
    list[float]
        A list of probabilities where:
        - The first element is the probability that the control variant is the best
        - Subsequent elements are the probabilities that each test variant is the best

    Notes:
    ------
    - Uses a Bayesian approach with Beta distributions as the posterior
    - Uses Beta(1,1) as the prior, which is uniform over [0,1]
    - Draws 10,000 samples from each variant's posterior distribution
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
    # Calculate probability of each variant being the best
    probabilities = []
    for i in range(len(all_variants)):
        probability = (samples_array[i] == np.max(samples_array, axis=0)).mean()
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
    of each variant, representing the range where we believe the true rate lies
    with 95% probability.

    Parameters:
    -----------
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of all variants including control, containing success and failure counts

    Returns:
    --------
    dict[str, list[float]]
        Dictionary mapping variant keys to [lower, upper] credible intervals, where:
        - lower is the 2.5th percentile of the posterior distribution
        - upper is the 97.5th percentile of the posterior distribution

    Notes:
    ------
    - Uses Beta distribution as the posterior
    - Uses Beta(1,1) as the prior, which is uniform over [0,1]
    - Returns 95% credible intervals
    - Intervals become narrower with larger sample sizes
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
