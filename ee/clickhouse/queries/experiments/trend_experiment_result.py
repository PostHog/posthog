import dataclasses
from datetime import datetime
from math import exp, lgamma, log
from typing import List, Optional, Tuple, Type

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

Probability = float
CONTROL_VARIANT_KEY = "control"


@dataclasses.dataclass
class Variant:
    key: str
    count: int
    exposure: int


class ClickhouseTrendExperimentResult:
    """
    This class calculates Experiment Results.
    It returns two things:
    1. A trend Breakdown based on Feature Flag values
    2. Probability that Feature Flag value 1 has better conversion rate then FeatureFlag value 2

    Currently, it only supports two feature flag values: control and test

    The passed in Filter determines which trend to create, along with the experiment start & end date values

    Calculating (2) uses the formula here: https://www.evanmiller.org/bayesian-ab-testing.html#count_ab
    """

    def __init__(
        self,
        filter: Filter,
        team: Team,
        feature_flag: FeatureFlag,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
        trend_class: Type[ClickhouseTrends] = ClickhouseTrends,
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
        self.query_filter = query_filter
        self.team = team
        self.insight = trend_class()

    def get_results(self):
        insight_results = self.insight.run(self.query_filter, self.team)
        control_variant, test_variants = self.get_variants(insight_results)

        probabilities = self.calculate_results(control_variant, test_variants)

        mapping = {
            variant.key: probability for variant, probability in zip([control_variant, *test_variants], probabilities)
        }

        return {"insight": insight_results, "probability": mapping, "filters": self.query_filter.to_dict()}

    def get_variants(self, insight_results):
        # this assumes the Trend insight is Cumulative
        control_variant = None
        test_variants = []

        for result in insight_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]
            if breakdown_value == CONTROL_VARIANT_KEY:
                # by default, all variants exposed for same duration, so same exposure value
                control_variant = Variant(key=breakdown_value, count=int(count), exposure=1)
            else:
                test_variants.append(Variant(breakdown_value, int(count), 1))

        return control_variant, test_variants

    @staticmethod
    def calculate_results(control_variant: Variant, test_variants: List[Variant]) -> List[Probability]:
        """
        Calculates probability that A is better than B. First variant is control, rest are test variants.

        Only supports 2 variants today
        """
        if not control_variant:
            raise ValidationError("No control variant data found", code="no_data")

        if len(test_variants) > 2:
            raise ValidationError("Can't calculate A/B test results for more than 3 variants", code="too_much_data")

        if len(test_variants) < 1:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        return calculate_probability_of_winning_for_each([control_variant, *test_variants])


def simulate_winning_variant_for_arrival_rates(target_variant: Variant, variants: List[Variant]) -> float:
    random_sampler = default_rng()
    simulations_count = 1_000_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
        # and beta = prior_failure + variant_failure
        samples = random_sampler.gamma(variant.count + 1, variant.exposure, simulations_count)
        variant_samples.append(samples)

    target_variant_samples = random_sampler.gamma(target_variant.count + 1, target_variant.exposure, simulations_count)

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
        probability = simulate_winning_variant_for_arrival_rates(variants[1], [variants[0]])
        return [1 - probability, probability]

    elif len(variants) == 3:
        probability_third_wins = simulate_winning_variant_for_arrival_rates(variants[2], [variants[0], variants[1]])
        probability_second_wins = simulate_winning_variant_for_arrival_rates(variants[1], [variants[0], variants[2]])
        return [1 - probability_third_wins - probability_second_wins, probability_second_wins, probability_third_wins]

    elif len(variants) == 4:
        probability_fourth_wins = simulate_winning_variant_for_arrival_rates(
            variants[3], [variants[0], variants[1], variants[2]]
        )
        probability_third_wins = simulate_winning_variant_for_arrival_rates(
            variants[2], [variants[0], variants[1], variants[3]]
        )
        probability_second_wins = simulate_winning_variant_for_arrival_rates(
            variants[1], [variants[0], variants[2], variants[3]]
        )
        return [
            1 - probability_fourth_wins - probability_third_wins - probability_second_wins,
            probability_second_wins,
            probability_third_wins,
            probability_fourth_wins,
        ]
    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")
