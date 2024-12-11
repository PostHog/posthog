from rest_framework.exceptions import ValidationError
from sentry_sdk import capture_exception
from posthog.hogql_queries.experiments import FF_DISTRIBUTION_THRESHOLD, MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats
from scipy.stats import t
import numpy as np

# Prior parameters (minimal prior knowledge)
MU_0 = 0.0  # Prior mean
KAPPA_0 = 1.0  # Prior strength for mean
ALPHA_0 = 1.0  # Prior shape for variance
BETA_0 = 1.0  # Prior scale for variance

SAMPLE_SIZE = 10000


def calculate_probabilities_v2_continuous(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[float]:
    """
    Calculate the win probabilities for each variant in an experiment using Bayesian analysis
    for continuous metrics (e.g., revenue).

    This function computes the probability that each variant is the best (i.e., has the highest
    mean value) compared to all other variants, including the control. It uses samples
    drawn from the posterior distributions of each variant's mean.

    Parameters:
    -----------
    control_variant : ExperimentVariantTrendsBaseStats
        Statistics for the control group, including mean value and exposure (number of users)
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
    - Uses a Bayesian approach with a t-distribution as the posterior
    - Assumes a Normal-Inverse-Gamma prior
    - Log-transforms the data to handle typical revenue distributions
    """
    if len(test_variants) >= 10:
        raise ValidationError("Can't calculate experiment results for more than 10 variants", code="too_much_data")
    if len(test_variants) < 1:
        raise ValidationError("Can't calculate experiment results for less than 2 variants", code="no_data")

    # Calculate posterior parameters for control
    log_control_mean = np.log(control_variant.count)  # Using count field to store mean value
    log_variance = 0.25  # Assumed variance in log-space

    # Update parameters for control
    kappa_n_control = KAPPA_0 + control_variant.exposure
    mu_n_control = (KAPPA_0 * MU_0 + control_variant.exposure * log_control_mean) / kappa_n_control
    alpha_n_control = ALPHA_0 + control_variant.exposure / 2
    beta_n_control = BETA_0 + 0.5 * control_variant.exposure * log_variance

    # Draw samples from control posterior
    control_posterior = t(
        df=2 * alpha_n_control, loc=mu_n_control, scale=np.sqrt(beta_n_control / (kappa_n_control * alpha_n_control))
    )
    samples_control = control_posterior.rvs(SAMPLE_SIZE)

    # Draw samples for each test variant
    test_samples = []
    for test in test_variants:
        log_test_mean = np.log(test.count)  # Using count field to store mean value

        kappa_n_test = KAPPA_0 + test.exposure
        mu_n_test = (KAPPA_0 * MU_0 + test.exposure * log_test_mean) / kappa_n_test
        alpha_n_test = ALPHA_0 + test.exposure / 2
        beta_n_test = BETA_0 + 0.5 * test.exposure * log_variance

        test_posterior = t(
            df=2 * alpha_n_test, loc=mu_n_test, scale=np.sqrt(beta_n_test / (kappa_n_test * alpha_n_test))
        )
        test_samples.append(test_posterior.rvs(SAMPLE_SIZE))

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
        - Probability value
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


def calculate_credible_intervals_v2_continuous(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate Bayesian credible intervals for each variant's mean value.

    Parameters:
    -----------
    variants : list[ExperimentVariantTrendsBaseStats]
        List of variants containing mean values and exposure data
    lower_bound : float, optional (default=0.025)
        Lower percentile for the credible interval (2.5% for 95% CI)
    upper_bound : float, optional (default=0.975)
        Upper percentile for the credible interval (97.5% for 95% CI)

    Returns:
    --------
    dict[str, tuple[float, float]]
        Dictionary mapping variant keys to their credible intervals
    """
    intervals = {}

    for variant in variants:
        try:
            # Log-transform the mean value
            log_mean = np.log(variant.count)  # Using count field to store mean value
            log_variance = 0.25

            # Calculate posterior parameters using absolute_exposure
            kappa_n = KAPPA_0 + variant.absolute_exposure
            mu_n = (KAPPA_0 * MU_0 + variant.absolute_exposure * log_mean) / kappa_n
            alpha_n = ALPHA_0 + variant.absolute_exposure / 2
            beta_n = BETA_0 + 0.5 * variant.absolute_exposure * log_variance

            # Create posterior distribution
            posterior = t(df=2 * alpha_n, loc=mu_n, scale=np.sqrt(beta_n / (kappa_n * alpha_n)))

            # Calculate credible intervals
            credible_interval = posterior.interval(upper_bound - lower_bound)

            # Transform back from log space
            intervals[variant.key] = (float(np.exp(credible_interval[0])), float(np.exp(credible_interval[1])))
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals
