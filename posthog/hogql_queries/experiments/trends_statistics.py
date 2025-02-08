from functools import lru_cache
from math import exp, lgamma, log, ceil

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError
import scipy.stats as stats
from posthog.exceptions_capture import capture_exception

from ee.clickhouse.queries.experiments import (
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
    P_VALUE_SIGNIFICANCE_LEVEL,
)

from posthog.schema import ExperimentSignificanceCode, ExperimentVariantTrendsBaseStats

Probability = float


def calculate_probabilities(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> list[Probability]:
    """
    Calculates probability that A is better than B. First variant is control, rest are test variants.

    Supports maximum 10 variants today

    For each variant, we create a Gamma distribution of arrival rates,
    where alpha (shape parameter) = count of variant + 1
    beta (exposure parameter) = 1
    """
    if not control_variant:
        raise ValidationError("No control variant data found", code="no_data")

    if len(test_variants) >= 10:
        raise ValidationError(
            "Can't calculate experiment results for more than 10 variants",
            code="too_much_data",
        )

    if len(test_variants) < 1:
        raise ValidationError(
            "Can't calculate experiment results for less than 2 variants",
            code="no_data",
        )

    variants = [control_variant, *test_variants]
    probabilities = []

    # simulate winning for each test variant
    for index, variant in enumerate(variants):
        probabilities.append(
            simulate_winning_variant_for_arrival_rates(variant, variants[:index] + variants[index + 1 :])
        )

    total_test_probabilities = sum(probabilities[1:])

    return [max(0, 1 - total_test_probabilities), *probabilities[1:]]


def simulate_winning_variant_for_arrival_rates(
    target_variant: ExperimentVariantTrendsBaseStats, variants: list[ExperimentVariantTrendsBaseStats]
) -> float:
    random_sampler = default_rng()
    simulations_count = 100_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Gamma distribution with alpha = variant_sucess + 1,
        # and exposure = relative exposure of variant
        samples = random_sampler.gamma(variant.count + 1, 1 / variant.exposure, simulations_count)
        variant_samples.append(samples)

    target_variant_samples = random_sampler.gamma(
        target_variant.count + 1, 1 / target_variant.exposure, simulations_count
    )

    winnings = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(ceil(simulations_count)):
        if target_variant_samples[i] > max(variant_conversions[i]):
            winnings += 1

    return winnings / simulations_count


def are_results_significant(
    control_variant: ExperimentVariantTrendsBaseStats,
    test_variants: list[ExperimentVariantTrendsBaseStats],
    probabilities: list[Probability],
) -> tuple[ExperimentSignificanceCode, Probability]:
    # TODO: Experiment with Expected Loss calculations for trend experiments

    for variant in test_variants:
        # We need a feature flag distribution threshold because distribution of people
        # can skew wildly when there are few people in the experiment
        if variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
            return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1

    if control_variant.absolute_exposure < FF_DISTRIBUTION_THRESHOLD:
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1

    if (
        probabilities[0] < MIN_PROBABILITY_FOR_SIGNIFICANCE
        and sum(probabilities[1:]) < MIN_PROBABILITY_FOR_SIGNIFICANCE
    ):
        # Sum of probability of winning for all variants except control is less than 90%
        return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1

    p_value = calculate_p_value(control_variant, test_variants)

    if p_value >= P_VALUE_SIGNIFICANCE_LEVEL:
        return ExperimentSignificanceCode.HIGH_P_VALUE, p_value

    return ExperimentSignificanceCode.SIGNIFICANT, p_value


@lru_cache(maxsize=100_000)
def combinationln(n: float, k: float) -> float:
    """
    Returns the log of the binomial coefficient.
    """
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


def intermediate_poisson_term(count: float, iterator: float, relative_exposure: float):
    return exp(
        combinationln(count, iterator)
        + iterator * log(relative_exposure)
        + (count - iterator) * log(1 - relative_exposure)
    )


def poisson_p_value(control_count, control_exposure, test_count, test_exposure):
    """
    Calculates the p-value of the experiment.
    Calculations from: https://www.evanmiller.org/statistical-formulas-for-programmers.html#count_test
    """
    relative_exposure = test_exposure / (control_exposure + test_exposure)
    total_count = control_count + test_count

    low_p_value = 0.0
    high_p_value = 0.0

    for i in range(ceil(test_count) + 1):
        low_p_value += intermediate_poisson_term(total_count, i, relative_exposure)

    for i in range(ceil(test_count), ceil(total_count) + 1):
        high_p_value += intermediate_poisson_term(total_count, i, relative_exposure)

    return min(1, 2 * min(low_p_value, high_p_value))


def calculate_p_value(
    control_variant: ExperimentVariantTrendsBaseStats, test_variants: list[ExperimentVariantTrendsBaseStats]
) -> Probability:
    best_test_variant = max(test_variants, key=lambda variant: variant.count)

    return poisson_p_value(
        control_variant.count,
        control_variant.exposure,
        best_test_variant.count,
        best_test_variant.exposure,
    )


def calculate_credible_intervals(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate the Bayesian credible intervals for the mean (average events per unit)
    for a list of variants in a Trend experiment.
    If no lower/upper bound is provided, the function calculates the 95% credible interval.
    """
    intervals = {}

    for variant in variants:
        try:
            # Alpha (shape parameter) is count + 1, assuming a Gamma distribution for counts
            alpha = variant.count + 1

            # Beta (scale parameter) is the inverse of absolute_exposure,
            # representing the average rate of events per user
            beta = 1 / variant.absolute_exposure

            # Calculate the credible interval for the mean using Gamma distribution
            credible_interval = stats.gamma.ppf([lower_bound, upper_bound], a=alpha, scale=beta)

            intervals[variant.key] = (credible_interval[0], credible_interval[1])

        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals
