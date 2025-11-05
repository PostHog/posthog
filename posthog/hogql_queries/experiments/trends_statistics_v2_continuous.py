import numpy as np
from rest_framework.exceptions import ValidationError
from scipy.stats import t

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.experiments import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)

# Prior parameters (minimal prior knowledge)
MU_0 = 0.0  # Prior mean
KAPPA_0 = 1.0  # Prior strength for mean
ALPHA_0 = 1.0  # Prior shape for variance
BETA_0 = 1.0  # Prior scale for variance

LOG_VARIANCE = 0.75

SAMPLE_SIZE = 10000
EPSILON = 1e-10  # Small epsilon value to handle zeros


def calculate_probabilities_v2_continuous(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Calculate the win probabilities for each variant in an experiment using Bayesian analysis
    for continuous metrics (e.g., revenue) with log-normal distribution assumptions.

    This function computes the probability that each variant is the best by comparing its
    posterior distribution against all other variants. It uses a Normal-Inverse-Gamma prior
    and performs analysis in log-space to handle right-skewed distributions typical of
    metrics like revenue.

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, containing the mean value (in count field)
        and exposure (number of users)
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
    - Uses log-transformation of data to handle right-skewed distributions
    - Employs a Normal-Inverse-Gamma prior with parameters:
      MU_0=0.0, KAPPA_0=1.0, ALPHA_0=1.0, BETA_0=1.0
    - Assumes constant variance in log-space (LOG_VARIANCE=0.75)
    - Draws SAMPLE_SIZE=10000 samples from each posterior for probability estimation

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantTrendsBaseStats
    >>> from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import calculate_probabilities_v2_continuous
    >>> control = ExperimentVariantTrendsBaseStats(
    ...     key="control",
    ...     count=50,  # mean revenue per user
    ...     exposure=1.0,  # exposure relative to control
    ...     absolute_exposure=500  # number of users
    ... )
    >>> test = ExperimentVariantTrendsBaseStats(
    ...     key="test",
    ...     count=60,  # mean revenue per user
    ...     exposure=1,  # exposure relative to control
    ...     absolute_exposure=500  # number of users
    ... )
    >>> calculate_probabilities_v2_continuous(control, [test])
    >>> # Returns: [0.0004, 0.9996] indicating the test variant is very likely to be best
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    mean_value_control = control_variant.count / control_variant.absolute_exposure

    # Calculate posterior parameters for control
    log_control_mean = np.log(mean_value_control + EPSILON)

    # Update parameters for control
    kappa_n_control = KAPPA_0 + control_variant.absolute_exposure
    mu_n_control = (KAPPA_0 * MU_0 + control_variant.absolute_exposure * log_control_mean) / kappa_n_control
    alpha_n_control = ALPHA_0 + control_variant.absolute_exposure / 2
    beta_n_control = BETA_0 + 0.5 * control_variant.absolute_exposure * LOG_VARIANCE

    # Draw samples from control posterior
    control_posterior = t(
        df=2 * alpha_n_control, loc=mu_n_control, scale=np.sqrt(beta_n_control / (kappa_n_control * alpha_n_control))
    )
    samples_control = control_posterior.rvs(SAMPLE_SIZE)

    # Draw samples for each test variant
    test_samples = []
    for test in test_variants:
        mean_value_test = test.count / test.absolute_exposure
        log_test_mean = np.log(mean_value_test + EPSILON)

        kappa_n_test = KAPPA_0 + test.absolute_exposure
        mu_n_test = (KAPPA_0 * MU_0 + test.absolute_exposure * log_test_mean) / kappa_n_test
        alpha_n_test = ALPHA_0 + test.absolute_exposure / 2
        beta_n_test = BETA_0 + 0.5 * test.absolute_exposure * LOG_VARIANCE

        test_posterior = t(
            df=2 * alpha_n_test, loc=mu_n_test, scale=np.sqrt(beta_n_test / (kappa_n_test * alpha_n_test))
        )
        test_samples.append(test_posterior.rvs(SAMPLE_SIZE))

    # Calculate probabilities
    probabilities = []

    # Probability control wins (beats the best test variant)
    best_test_samples = np.max(test_samples, axis=0)  # Get best test variant at each sample point
    control_wins = samples_control > best_test_samples
    probabilities.append(float(np.mean(control_wins)))

    # Probability each test variant wins (beats control only)
    for test_sample in test_samples:
        variant_wins = test_sample > samples_control
        probabilities.append(float(np.mean(variant_wins)))

    return probabilities


def are_results_significant_v2_continuous(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[float],
) -> tuple[ExperimentSignificanceCode, float]:
    """
    Determines if experiment results are statistically significant using Bayesian analysis
    for continuous metrics.

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group
    test_variants : list[ExperimentVariantTrendsBaseStats]
        List of statistics for test variants to compare against control
    probabilities : list[float]
        List of win probabilities for each variant

    Returns:
    --------
    tuple[ExperimentSignificanceCode, float]
        - ExperimentSignificanceCode indicating the significance status
        - Expected loss value for significant results, 1.0 for non-significant results
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
        means = [v.count for v in all_variants]  # count field stores mean value
        best_idx = np.argmax(means)
        best_variant = all_variants[best_idx]
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1 :]

        expected_loss = calculate_expected_loss_v2_continuous(best_variant, other_variants)

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1.0


def calculate_credible_intervals_v2_continuous(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate Bayesian credible intervals for each variant's mean value using a log-normal model.

    This function computes credible intervals in log-space using a t-distribution posterior
    derived from a Normal-Inverse-Gamma prior, then transforms the results back to the original
    scale. This approach is particularly suitable for right-skewed metrics like revenue.

    Parameters:
    -----------
    variants : list[ExperimentVariantTrendsBaseStats]
        List of variants where each variant contains:
        - count: the mean value of the metric
        - absolute_exposure: number of users/observations
        - key: identifier for the variant
    lower_bound : float, optional (default=0.025)
        Lower percentile for the credible interval (2.5% for 95% CI)
    upper_bound : float, optional (default=0.975)
        Upper percentile for the credible interval (97.5% for 95% CI)

    Returns:
    --------
    dict[str, tuple[float, float]]
        Dictionary mapping variant keys to their credible intervals where:
        - Key: variant identifier
        - Value: tuple of (lower_bound, upper_bound) in original scale
        Returns empty dict if any calculation errors occur

    Notes:
    ------
    - Uses log-transformation to handle right-skewed distributions
    - Employs Normal-Inverse-Gamma prior with parameters:
      MU_0=0.0, KAPPA_0=1.0, ALPHA_0=1.0, BETA_0=1.0
    - Assumes constant variance in log-space (LOG_VARIANCE=0.75)
    - Results are transformed back to original scale and guaranteed non-negative
    - Handles potential calculation errors gracefully by returning empty dict

    Example:
    --------
    >>> from posthog.schema import ExperimentVariantTrendsBaseStats
    >>> from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import calculate_credible_intervals_v2_continuous
    >>> variants = [
    ...     ExperimentVariantTrendsBaseStats(
    ...         key="control",
    ...         count=50.0,  # mean revenue per user
    ...         exposure=1.0,  # exposure relative to control
    ...         absolute_exposure=500  # number of users
    ...     ),
    ...     ExperimentVariantTrendsBaseStats(
    ...         key="test",
    ...         count=60.0,  # mean revenue per user
    ...         exposure=1,  # exposure relative to control
    ...         absolute_exposure=500  # number of users
    ...     )
    ... ]
    >>> calculate_credible_intervals_v2_continuous(variants)
    >>> # Returns something like:
    >>> # {
    >>> #     'control': (45.98, 53.53),  # 95% confident true mean is between $45.98-$53.53
    >>> #     'test': (55.15, 64.22)     # 95% confident true mean is between $55.15-$64.22
    >>> # }
    """
    intervals = {}

    for variant in variants:
        try:
            # Log-transform the mean value, adding epsilon to handle zeros
            mean_value = variant.count / variant.absolute_exposure
            log_mean = np.log(mean_value + EPSILON)

            # Calculate posterior parameters using absolute_exposure
            kappa_n = KAPPA_0 + variant.absolute_exposure
            mu_n = (KAPPA_0 * MU_0 + variant.absolute_exposure * log_mean) / kappa_n
            alpha_n = ALPHA_0 + variant.absolute_exposure / 2
            beta_n = BETA_0 + 0.5 * variant.absolute_exposure * LOG_VARIANCE

            # Create posterior distribution
            posterior = t(df=2 * alpha_n, loc=mu_n, scale=np.sqrt(beta_n / (kappa_n * alpha_n)))

            # Calculate credible intervals
            credible_interval = posterior.interval(upper_bound - lower_bound)

            # Transform back from log space and subtract epsilon
            intervals[variant.key] = (
                float(max(0, np.exp(credible_interval[0]) - EPSILON)),  # Ensure non-negative
                float(max(0, np.exp(credible_interval[1]) - EPSILON)),  # Ensure non-negative
            )
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals


def calculate_expected_loss_v2_continuous(
    target_variant: ExperimentVariantTrendsBaseStats, variants: list[ExperimentVariantTrendsBaseStats]
) -> float:
    """
    Calculates expected loss in mean value using Normal-Inverse-Gamma conjugate prior.

    This implementation uses a Bayesian approach with Normal-Inverse-Gamma model
    to estimate the expected loss when choosing the target variant over others.
    The data is log-transformed to handle typical revenue/continuous metric distributions.

    Parameters:
    -----------
    target_variant : ExperimentVariantTrendsBaseStats
        The variant being evaluated for loss
    variants : list[ExperimentVariantTrendsBaseStats]
        List of other variants to compare against

    Returns:
    --------
    float
        Expected loss in mean value if choosing the target variant
    """
    # Calculate posterior parameters for target variant
    target_mean = target_variant.count / target_variant.absolute_exposure
    log_target_mean = np.log(target_mean + EPSILON)

    # Update parameters for target variant
    kappa_n_target = KAPPA_0 + target_variant.absolute_exposure
    mu_n_target = (KAPPA_0 * MU_0 + target_variant.absolute_exposure * log_target_mean) / kappa_n_target
    alpha_n_target = ALPHA_0 + target_variant.absolute_exposure / 2
    beta_n_target = BETA_0 + 0.5 * target_variant.absolute_exposure * LOG_VARIANCE

    # Draw samples from target variant's posterior
    target_posterior = t(
        df=2 * alpha_n_target, loc=mu_n_target, scale=np.sqrt(beta_n_target / (kappa_n_target * alpha_n_target))
    )
    target_samples = target_posterior.rvs(SAMPLE_SIZE)

    # Draw samples from each comparison variant's posterior
    variant_samples = []
    for variant in variants:
        variant_mean = variant.count / variant.absolute_exposure
        log_variant_mean = np.log(variant_mean + EPSILON)

        kappa_n = KAPPA_0 + variant.absolute_exposure
        mu_n = (KAPPA_0 * MU_0 + variant.absolute_exposure * log_variant_mean) / kappa_n
        alpha_n = ALPHA_0 + variant.absolute_exposure / 2
        beta_n = BETA_0 + 0.5 * variant.absolute_exposure * LOG_VARIANCE

        variant_posterior = t(df=2 * alpha_n, loc=mu_n, scale=np.sqrt(beta_n / (kappa_n * alpha_n)))
        variant_samples.append(variant_posterior.rvs(SAMPLE_SIZE))

    # Transform samples back from log space
    target_samples = np.exp(target_samples) - EPSILON
    variant_samples = [np.exp(samples) - EPSILON for samples in variant_samples]

    # Calculate loss
    variant_max = np.maximum.reduce(variant_samples)
    losses = np.maximum(0, variant_max - target_samples)
    expected_loss = float(np.mean(losses))

    return expected_loss
