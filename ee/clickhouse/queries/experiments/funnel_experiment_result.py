from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Type

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.experiments import (
    CONTROL_VARIANT_KEY,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)
from ee.clickhouse.queries.funnels import ClickhouseFunnel
from posthog.constants import ExperimentSignificanceCode
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

Probability = float


@dataclass(frozen=True)
class Variant:
    key: str
    success_count: int
    failure_count: int


EXPECTED_LOSS_SIGNIFICANCE_LEVEL = 0.01


class ClickhouseFunnelExperimentResult:
    """
    This class calculates Experiment Results.
    It returns two things:
    1. A Funnel Breakdown based on Feature Flag values
    2. Probability that Feature Flag value 1 has better conversion rate then FeatureFlag value 2

    Currently, we support a maximum of 4 feature flag values: control and 3 test variants

    The passed in Filter determines which funnel to create, along with the experiment start & end date values

    Calculating (2) uses sampling from a Beta distribution. If `control` value for the feature flag has 10 successes and 12 conversion failures,
    we assume the conversion rate follows a Beta(10, 12) distribution. Same for `test` variant.

    Then, we calculcate how many times a sample from `test` variant is higher than a sample from the `control` variant. This becomes the
    probability.
    """

    def __init__(
        self,
        filter: Filter,
        team: Team,
        feature_flag: FeatureFlag,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
        funnel_class: Type[ClickhouseFunnel] = ClickhouseFunnel,
    ):

        breakdown_key = f"$feature/{feature_flag.key}"
        variants = [variant["key"] for variant in feature_flag.variants]

        query_filter = filter.with_data(
            {
                "date_from": experiment_start_date,
                "date_to": experiment_end_date,
                "breakdown": breakdown_key,
                "breakdown_type": "event",
                "properties": [{"key": breakdown_key, "value": variants, "operator": "exact", "type": "event"}],
                # :TRICKY: We don't use properties set on filters, instead using experiment variant options
            }
        )
        self.funnel = funnel_class(query_filter, team)

    def get_results(self):
        funnel_results = self.funnel.run()
        control_variant, test_variants = self.get_variants(funnel_results)

        probabilities = self.calculate_results(control_variant, test_variants)

        mapping = {
            variant.key: probability for variant, probability in zip([control_variant, *test_variants], probabilities)
        }

        significance_code, loss = self.are_results_significant(control_variant, test_variants, probabilities)

        return {
            "insight": funnel_results,
            "probability": mapping,
            "significant": significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            "filters": self.funnel._filter.to_dict(),
            "significance_code": significance_code,
            "expected_loss": loss,
            "variants": [asdict(variant) for variant in [control_variant, *test_variants]],
        }

    def get_variants(self, funnel_results):
        control_variant = None
        test_variants = []
        for result in funnel_results:
            total = result[0]["count"]
            success = result[-1]["count"]
            failure = total - success
            breakdown_value = result[0]["breakdown_value"][0]
            if breakdown_value == CONTROL_VARIANT_KEY:
                control_variant = Variant(key=breakdown_value, success_count=int(success), failure_count=int(failure))
            else:
                test_variants.append(Variant(breakdown_value, int(success), int(failure)))

        return control_variant, test_variants

    @staticmethod
    def calculate_results(
        control_variant: Variant, test_variants: List[Variant], priors: Tuple[int, int] = (1, 1)
    ) -> List[Probability]:
        """
        Calculates probability that A is better than B. First variant is control, rest are test variants.

        Supports maximum 4 variants today

        For each variant, we create a Beta distribution of conversion rates,
        where alpha (successes) = success count of variant + prior success
        beta (failures) = failure count + variant + prior failures

        The prior is information about the world we already know. For example, a stronger prior for failures implies
        you'd need extra evidence of successes to confirm that the variant is indeed better.

        By default, we choose a non-informative prior. That is, both success & failure are equally likely.
        """

        if not control_variant:
            raise ValidationError("No control variant data found", code="no_data")

        if len(test_variants) > 3:
            raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")

        if len(test_variants) < 1:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        return calculate_probability_of_winning_for_each([control_variant, *test_variants])

    @staticmethod
    def are_results_significant(
        control_variant: Variant, test_variants: List[Variant], probabilities: List[Probability]
    ) -> Tuple[ExperimentSignificanceCode, Probability]:
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
            test_variants, key=lambda variant: variant.success_count / (variant.success_count + variant.failure_count)
        )

        expected_loss = calculate_expected_loss(best_test_variant, [control_variant])

        if expected_loss >= EXPECTED_LOSS_SIGNIFICANCE_LEVEL:
            return ExperimentSignificanceCode.HIGH_LOSS, expected_loss

        return ExperimentSignificanceCode.SIGNIFICANT, expected_loss


def calculate_expected_loss(target_variant: Variant, variants: List[Variant]) -> float:
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
            variant.success_count + prior_success, variant.failure_count + prior_failure, simulations_count
        )
        variant_samples.append(samples)

    target_variant_samples = random_sampler.beta(
        target_variant.success_count + prior_success, target_variant.failure_count + prior_failure, simulations_count
    )

    loss = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(simulations_count):
        loss += max(0, max(variant_conversions[i]) - target_variant_samples[i])

    return loss / simulations_count


def simulate_winning_variant_for_conversion(target_variant: Variant, variants: List[Variant]) -> Probability:
    random_sampler = default_rng()
    prior_success = 1
    prior_failure = 1
    simulations_count = 100_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
        # and beta = prior_failure + variant_failure
        samples = random_sampler.beta(
            variant.success_count + prior_success, variant.failure_count + prior_failure, simulations_count
        )
        variant_samples.append(samples)

    target_variant_samples = random_sampler.beta(
        target_variant.success_count + prior_success, target_variant.failure_count + prior_failure, simulations_count
    )

    winnings = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(simulations_count):
        if target_variant_samples[i] > max(variant_conversions[i]):
            winnings += 1

    return winnings / simulations_count


def calculate_probability_of_winning_for_each(variants: List[Variant]) -> List[Probability]:
    """
    Calculates the probability of winning for each variant.
    """
    if len(variants) == 2:
        # simple case
        probability = simulate_winning_variant_for_conversion(variants[1], [variants[0]])
        return [max(0, 1 - probability), probability]

    elif len(variants) == 3:
        probability_third_wins = simulate_winning_variant_for_conversion(variants[2], [variants[0], variants[1]])
        probability_second_wins = simulate_winning_variant_for_conversion(variants[1], [variants[0], variants[2]])
        return [
            max(0, 1 - probability_third_wins - probability_second_wins),
            probability_second_wins,
            probability_third_wins,
        ]

    elif len(variants) == 4:
        probability_second_wins = simulate_winning_variant_for_conversion(
            variants[1], [variants[0], variants[2], variants[3]]
        )
        probability_third_wins = simulate_winning_variant_for_conversion(
            variants[2], [variants[0], variants[1], variants[3]]
        )
        probability_fourth_wins = simulate_winning_variant_for_conversion(
            variants[3], [variants[0], variants[1], variants[2]]
        )
        return [
            max(0, 1 - probability_second_wins - probability_third_wins - probability_fourth_wins),
            probability_second_wins,
            probability_third_wins,
            probability_fourth_wins,
        ]
    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")
