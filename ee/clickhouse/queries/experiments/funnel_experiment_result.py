import dataclasses
from datetime import datetime
from typing import List, Optional, Tuple, Type

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels import ClickhouseFunnel
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

Probability = float


@dataclasses.dataclass
class Variant:
    key: str
    success_count: int
    failure_count: int


SIMULATION_COUNT = 100_000
CONTROL_VARIANT_KEY = "control"


class ClickhouseFunnelExperimentResult:
    """
    This class calculates Experiment Results.
    It returns two things:
    1. A Funnel Breakdown based on Feature Flag values
    2. Probability that Feature Flag value 1 has better conversion rate then FeatureFlag value 2

    Currently, it only supports two feature flag values: control and test

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

        return {"insight": funnel_results, "probability": mapping, "filters": self.funnel._filter.to_dict()}

    def get_variants(self, funnel_results):
        control_variant = None
        test_variants = []
        for result in funnel_results:
            total = sum([step["count"] for step in result])
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


def simulate_winning_variant_for_conversion(target_variant: Variant, variants: List[Variant]) -> float:
    random_sampler = default_rng()
    prior_success = 1
    prior_failure = 1
    simulations_count = 1_000_000

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
        return [1 - probability, probability]

    elif len(variants) == 3:
        probability_third_wins = simulate_winning_variant_for_conversion(variants[2], [variants[0], variants[1]])
        probability_second_wins = simulate_winning_variant_for_conversion(variants[1], [variants[0], variants[2]])
        return [1 - probability_third_wins - probability_second_wins, probability_second_wins, probability_third_wins]

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
            1 - probability_second_wins - probability_third_wins - probability_fourth_wins,
            probability_second_wins,
            probability_third_wins,
            probability_fourth_wins,
        ]
    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")
