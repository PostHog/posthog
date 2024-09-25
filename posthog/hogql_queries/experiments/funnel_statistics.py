from dataclasses import dataclass
from rest_framework.exceptions import ValidationError
from numpy.random import default_rng
from sentry_sdk import capture_exception
import scipy.stats as stats
from posthog.constants import ExperimentSignificanceCode
from posthog.hogql_queries.experiments import (
    EXPECTED_LOSS_SIGNIFICANCE_LEVEL,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)


@dataclass(frozen=True)
class Variant:
    key: str
    success_count: int
    failure_count: int


Probability = float


def calculate_probabilities(
    control_variant: Variant,
    test_variants: list[Variant],
    priors: tuple[int, int] = (1, 1),
) -> list[Probability]:
    """
    Calculates the probability that each variant outperforms the others.

    Supports up to 10 variants (1 control + 9 test).

    Method:
    1. For each variant, create a Beta distribution of conversion rates:
        α (alpha) = success count of variant + prior success
        β (beta) = failure count + variant + prior failures
    2. Use Monte Carlo simulation to estimate winning probabilities.

    The prior represents our initial belief about conversion rates.
    We use a non-informative prior (1, 1) by default, assuming equal
    likelihood of success and failure.

    Returns: List of probabilities, where index 0 is control.
    """

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
        probabilities.append(simulate_winning_variant_for_conversion(variant, variants[:index] + variants[index + 1 :]))

    total_test_probabilities = sum(probabilities[1:])

    return [max(0, 1 - total_test_probabilities), *probabilities[1:]]


def simulate_winning_variant_for_conversion(target_variant: Variant, variants: list[Variant]) -> Probability:
    random_sampler = default_rng()
    prior_success = 1
    prior_failure = 1
    simulations_count = 100_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
        # and beta = prior_failure + variant_failure
        samples = random_sampler.beta(
            variant.success_count + prior_success,
            variant.failure_count + prior_failure,
            simulations_count,
        )
        variant_samples.append(samples)

    target_variant_samples = random_sampler.beta(
        target_variant.success_count + prior_success,
        target_variant.failure_count + prior_failure,
        simulations_count,
    )

    winnings = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(simulations_count):
        if target_variant_samples[i] > max(variant_conversions[i]):
            winnings += 1

    return winnings / simulations_count


def are_results_significant(
    control_variant: Variant,
    test_variants: list[Variant],
    probabilities: list[Probability],
) -> tuple[ExperimentSignificanceCode, Probability]:
    def get_conversion_rate(variant: Variant):
        return variant.success_count / (variant.success_count + variant.failure_count)

    control_sample_size = control_variant.success_count + control_variant.failure_count

    for variant in test_variants:
        # We need a feature flag distribution threshold because distribution of people
        # can skew wildly when there are few people in the experiment
        if variant.success_count + variant.failure_count < FF_DISTRIBUTION_THRESHOLD:
            return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1

    if control_sample_size < FF_DISTRIBUTION_THRESHOLD:
        return ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, 1

    if (
        probabilities[0] < MIN_PROBABILITY_FOR_SIGNIFICANCE
        and sum(probabilities[1:]) < MIN_PROBABILITY_FOR_SIGNIFICANCE
    ):
        # Sum of probability of winning for all variants except control is less than 90%
        return ExperimentSignificanceCode.LOW_WIN_PROBABILITY, 1

    best_test_variant = max(
        test_variants,
        key=lambda variant: get_conversion_rate(variant),
    )

    if get_conversion_rate(best_test_variant) > get_conversion_rate(control_variant):
        expected_loss = calculate_expected_loss(best_test_variant, [control_variant])
    else:
        expected_loss = calculate_expected_loss(control_variant, [best_test_variant])

    if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
        return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

    return ExperimentSignificanceCode.SIGNIFICANT, expected_loss


def calculate_expected_loss(target_variant: Variant, variants: list[Variant]) -> float:
    """
    Calculates expected loss in conversion rate for a given variant.
    Loss calculation comes from VWO's SmartStats technical paper:
    https://cdn2.hubspot.net/hubfs/310840/VWO_SmartStats_technical_whitepaper.pdf (pg 12)

    > The loss function is the amount of uplift that one can expect to
    be lost by choosing a given variant, given particular values of λA and λB

    The unit of the return value is conversion rate values

    """
    random_sampler = default_rng()
    prior_success = 1
    prior_failure = 1
    simulations_count = 100_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
        # and beta = prior_failure + variant_failure
        samples = random_sampler.beta(
            variant.success_count + prior_success,
            variant.failure_count + prior_failure,
            simulations_count,
        )
        variant_samples.append(samples)

    target_variant_samples = random_sampler.beta(
        target_variant.success_count + prior_success,
        target_variant.failure_count + prior_failure,
        simulations_count,
    )

    loss = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(simulations_count):
        loss += max(0, max(variant_conversions[i]) - target_variant_samples[i])

    return loss / simulations_count


def calculate_credible_intervals(variants, lower_bound=0.025, upper_bound=0.975):
    """
    Calculate the Bayesian credible intervals for a list of variants.
    If no lower/upper bound provided, the function calculates the 95% credible interval.
    """
    intervals = {}

    for variant in variants:
        try:
            if variant.success_count < 0 or variant.failure_count < 0:
                capture_exception(
                    Exception("Invalid variant success/failure count"),
                    {
                        "variant": variant.key,
                        "success_count": variant.success_count,
                        "failure_count": variant.failure_count,
                    },
                )
                return {}

            # Calculate the credible interval
            # Laplace smoothing: we add 1 to alpha and beta to avoid division errors if either is zero
            alpha = variant.success_count + 1
            beta = variant.failure_count + 1
            credible_interval = stats.beta.ppf([lower_bound, upper_bound], alpha, beta)

            intervals[variant.key] = (credible_interval[0], credible_interval[1])
        except Exception as e:
            capture_exception(
                Exception(f"Error calculating credible interval for variant {variant.key}"),
                {"error": str(e)},
            )
            return {}

    return intervals
