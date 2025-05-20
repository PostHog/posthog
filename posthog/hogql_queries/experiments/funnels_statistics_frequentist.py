import numpy as np
from scipy import stats
from typing import Optional
from posthog.schema import ExperimentVariantFunnelsBaseStats, ExperimentSignificanceCode
from posthog.hogql_queries.experiments import (
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
)

# P-value threshold for significance
P_VALUE_THRESHOLD = 0.05


def calculate_conversion_rate_and_ci(success_count: float, failure_count: float, confidence: float = 0.95) -> tuple[float, float, float]:
    """
    Calculate the conversion rate and confidence interval using a frequentist approach.
    
    Parameters:
    -----------
    success_count : float
        Number of conversions (successes)
    failure_count : float
        Number of non-conversions (failures)
    confidence : float, optional
        Confidence level (default: 0.95 for 95% confidence)
        
    Returns:
    --------
    tuple[float, float, float]
        Conversion rate, lower bound, and upper bound of the confidence interval
    """
    total = success_count + failure_count
    if total == 0:
        return 0.0, 0.0, 0.0

    # Calculate conversion rate
    conversion_rate = success_count / total

    # Calculate confidence interval using normal approximation (with continuity correction)
    # This is valid for large samples; we'll use Wilson score interval for smaller samples
    if total >= 30 and success_count >= 5 and failure_count >= 5:
        # Normal approximation confidence interval
        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        # Standard error with continuity correction
        standard_error = np.sqrt(conversion_rate * (1 - conversion_rate) / total)
        margin_of_error = z * standard_error

        lower_bound = max(0.0, conversion_rate - margin_of_error)
        upper_bound = min(1.0, conversion_rate + margin_of_error)
    else:
        # Wilson score interval for smaller samples
        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        denominator = 1 + z**2 / total

        center = (conversion_rate + z**2 / (2 * total)) / denominator
        adjustment = z * np.sqrt(conversion_rate * (1 - conversion_rate) / total + z**2 / (4 * total**2)) / denominator

        lower_bound = max(0.0, center - adjustment)
        upper_bound = min(1.0, center + adjustment)

    return conversion_rate, lower_bound, upper_bound


def calculate_p_value(
    control: ExperimentVariantFunnelsBaseStats,
    variant: ExperimentVariantFunnelsBaseStats
) -> float:
    """
    Calculate the p-value for a two-proportion z-test between control and variant.
    
    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Control variant statistics
    variant : ExperimentVariantFunnelsBaseStats
        Test variant statistics
        
    Returns:
    --------
    float
        Two-tailed p-value for the difference in proportions
    """
    control_success = control.success_count
    control_total = control.success_count + control.failure_count

    variant_success = variant.success_count
    variant_total = variant.success_count + variant.failure_count

    # If either variant has no data, return a non-significant p-value (1.0)
    if control_total == 0 or variant_total == 0:
        return 1.0

    # Convert to proportions
    control_prop = control_success / control_total
    variant_prop = variant_success / variant_total

    # We use the two-proportion z-test
    # Pooled proportion for standard error
    pooled_prop = (control_success + variant_success) / (control_total + variant_total)

    # Standard error of the difference between proportions
    se = np.sqrt(pooled_prop * (1 - pooled_prop) * (1/control_total + 1/variant_total))

    # If standard error is 0 (extremely rare), return 1.0 (non-significant)
    if se == 0:
        return 1.0

    # Calculate z-statistic
    z = (variant_prop - control_prop) / se

    # Two-tailed p-value
    p_value = 2 * stats.norm.sf(abs(z))

    return p_value


def calculate_p_values(
    control: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats]
) -> list[float]:
    """
    Calculate p-values for each test variant compared to control.
    
    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Control variant statistics
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of test variants to compare against control
        
    Returns:
    --------
    list[float]
        List of p-values [control_vs_best, variant1_vs_control, variant2_vs_control, ...]
    """
    # Calculate p-values for each test variant compared to control
    variant_p_values = [calculate_p_value(control, variant) for variant in variants]

    # For the control, we need to compare it with the best-performing variant
    if variants:
        conversion_rates = [variant.success_count / max(1, variant.success_count + variant.failure_count) for variant in variants]
        best_variant_idx = np.argmax(conversion_rates)
        control_p_value = calculate_p_value(variants[best_variant_idx], control)
    else:
        control_p_value = 1.0

    # Return the p-values in the format [control_vs_best, variant1_vs_control, variant2_vs_control, ...]
    return [control_p_value] + variant_p_values


def calculate_probabilities_frequentist(
    control: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats]
) -> list[float]:
    """
    Calculate win probabilities for each variant based on frequentist p-values.
    
    The function converts p-values into win probabilities in a way that's compatible
    with the Bayesian interface expected by the experiment query runner.
    
    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Control variant statistics
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of test variants to compare against control
        
    Returns:
    --------
    list[float]
        List of probabilities:
        - index 0: probability control beats the best test variant
        - index i>0: probability test variant i-1 beats control
    """
    # Calculate p-values first
    p_values = calculate_p_values(control, variants)

    # Convert p-values to probabilities (1 - p_value)
    # This is a simplification that makes the interface compatible with Bayesian
    probabilities = [max(0.0, min(1.0, 1.0 - p)) for p in p_values]

    # For very small p-values, we want to set the probability close to 1 but not exactly 1
    # For very large p-values, we want to set the probability close to 0 but not exactly 0
    probabilities = [max(0.001, min(0.999, p)) for p in probabilities]

    return probabilities


def calculate_expected_lift(
    control: ExperimentVariantFunnelsBaseStats,
    variant: ExperimentVariantFunnelsBaseStats
) -> float:
    """
    Calculate the expected lift (relative improvement) from control to variant.
    
    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Control variant statistics
    variant : ExperimentVariantFunnelsBaseStats
        Test variant to compare against control
        
    Returns:
    --------
    float
        Expected lift as a decimal (e.g., 0.1 means 10% improvement)
    """
    control_total = control.success_count + control.failure_count
    variant_total = variant.success_count + variant.failure_count

    if control_total == 0 or variant_total == 0:
        return 0.0

    control_rate = control.success_count / control_total
    variant_rate = variant.success_count / variant_total

    # Avoid division by zero
    if control_rate == 0:
        return 1.0 if variant_rate > 0 else 0.0

    # Calculate relative improvement (as a decimal)
    return (variant_rate - control_rate) / control_rate


def calculate_expected_loss_frequentist(
    target_variant: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats]
) -> float:
    """
    Calculate expected loss if choosing the target variant over others.
    
    In frequentist terms, this estimates the opportunity cost of choosing
    the target variant instead of potentially better alternatives.
    
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
    target_total = target_variant.success_count + target_variant.failure_count

    if target_total == 0 or not variants:
        return 0.0

    target_rate = target_variant.success_count / target_total

    # Calculate conversion rates for all variants
    variant_rates = []
    for variant in variants:
        variant_total = variant.success_count + variant.failure_count
        if variant_total == 0:
            variant_rates.append(0.0)
        else:
            variant_rates.append(variant.success_count / variant_total)

    # Find the maximum rate from other variants
    max_other_rate = max(variant_rates)

    # Expected loss is the positive difference between max rate and target rate
    return max(0.0, max_other_rate - target_rate)


def are_results_significant_frequentist(
    control: ExperimentVariantFunnelsBaseStats,
    variants: list[ExperimentVariantFunnelsBaseStats],
    probabilities: Optional[list[float]] = None
) -> tuple[ExperimentSignificanceCode, float]:
    """
    Determine if the experiment results are statistically significant using frequentist methods.
    
    Parameters:
    -----------
    control : ExperimentVariantFunnelsBaseStats
        Statistics for the control group
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of statistics for test variants to compare against control
    probabilities : Optional[list[float]], optional
        Pre-calculated probabilities (will be calculated if not provided)
        
    Returns:
    --------
    tuple[ExperimentSignificanceCode, float]
        A tuple containing:
        - Significance code indicating the result
        - Expected loss value for significant results, otherwise p-value
    """
    # Check minimum exposure
    if control.success_count + control.failure_count < FF_DISTRIBUTION_THRESHOLD or any(
        v.success_count + v.failure_count < FF_DISTRIBUTION_THRESHOLD for v in variants
    ):
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1.0

    # Calculate p-values if probabilities aren't provided
    if probabilities is None:
        probabilities = calculate_probabilities_frequentist(control, variants)

    # Check if any variant has high enough probability (low enough p-value)
    max_probability = max(probabilities)
    if max_probability >= MIN_PROBABILITY_FOR_SIGNIFICANCE:
        # Find best performing variant
        all_variants = [control] + variants
        conversion_rates = [v.success_count / (v.success_count + v.failure_count) for v in all_variants]
        best_idx = np.argmax(conversion_rates)
        best_variant = all_variants[best_idx]

        # If we have a winner, calculate expected loss
        other_variants = all_variants[:best_idx] + all_variants[best_idx + 1:]
        expected_loss = calculate_expected_loss_frequentist(best_variant, other_variants)

        # Check if expected loss is too high
        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss

    # If p-value is too high, we don't have significance
    return ExperimentSignificanceCode.HIGH_P_VALUE, 1.0 - max_probability


def calculate_confidence_intervals_frequentist(
    variants: list[ExperimentVariantFunnelsBaseStats],
    confidence: float = 0.95
) -> dict[str, list[float]]:
    """
    Calculate frequentist confidence intervals for conversion rates of each variant.
    
    Parameters:
    -----------
    variants : list[ExperimentVariantFunnelsBaseStats]
        List of all variants (including control)
    confidence : float, optional
        Confidence level (default: 0.95 for 95% confidence)
        
    Returns:
    --------
    dict[str, list[float]]
        Dictionary mapping variant keys to [lower, upper] confidence intervals
    """
    intervals = {}

    for variant in variants:
        success_count = variant.success_count
        failure_count = variant.failure_count

        # Calculate conversion rate and confidence interval
        _, lower_bound, upper_bound = calculate_conversion_rate_and_ci(
            success_count, failure_count, confidence
        )

        intervals[variant.key] = [float(lower_bound), float(upper_bound)]

    return intervals
