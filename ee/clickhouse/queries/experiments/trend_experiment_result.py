import dataclasses
from datetime import datetime
from math import exp, lgamma, log
from typing import List, Optional, Tuple, Type

from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.util import logbeta
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

Probability = float
CONTROL_VARIANT_KEY = "control"


@dataclasses.dataclass
class Variant:
    name: str
    count: int


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
            variant.name: probability for variant, probability in zip([control_variant, *test_variants], probabilities)
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
                control_variant = Variant(name=breakdown_value, count=int(count))
            else:
                test_variants.append(Variant(breakdown_value, int(count)))

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

        # second calculation:
        # https://www.evanmiller.org/bayesian-ab-testing.html#count_ab

        control_count = 1 + control_variant.count
        control_exposure = 1
        test_exposure = 1  # by default, all variants exposed for same duration

        test_counts_and_exposure = [(1 + variant.count, test_exposure) for variant in test_variants]

        return calculate_probability_of_winning_for_each([(control_count, control_exposure), *test_counts_and_exposure])


def calculate_probability_of_winning_for_each(variants: List[Tuple[int, int]]) -> List[Probability]:
    """
    Calculates the probability of winning for each variant.
    """
    if len(variants) == 2:
        # simple case
        probability = probability_B_beats_A_count_data(variants[0][0], variants[0][1], variants[1][0], variants[1][1])
        return [1 - probability, probability]

    elif len(variants) == 3:
        probability_third_wins = probability_C_beats_A_and_B_count_data(
            variants[0][0], variants[0][1], variants[1][0], variants[1][1], variants[2][0], variants[2][1]
        )
        probability_second_wins = probability_C_beats_A_and_B_count_data(
            variants[0][0], variants[0][1], variants[2][0], variants[2][1], variants[1][0], variants[1][1]
        )
        return [1 - probability_third_wins - probability_second_wins, probability_second_wins, probability_third_wins]

    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")


def probability_B_beats_A_count_data(A_count: int, A_exposure: int, B_count: int, B_exposure: int) -> Probability:
    total: Probability = 0
    for i in range(B_count):
        total += exp(
            i * log(B_exposure)
            + A_count * log(A_exposure)
            - (i + A_count) * log(B_exposure + A_exposure)
            - log(i + A_count)
            - logbeta(i + 1, A_count)
        )

    return total


def probability_C_beats_A_and_B_count_data(
    A_count: int, A_exposure: int, B_count: int, B_exposure: int, C_count: int, C_exposure: int
) -> Probability:
    total: Probability = 0

    for k in range(B_count):
        for l in range(A_count):
            total += exp(
                k * log(B_exposure)
                + l * log(A_exposure)
                + C_count * log(C_exposure)
                - (k + l + C_count) * log(B_exposure + A_exposure + C_exposure)
                + lgamma(k + l + C_count)
                - lgamma(k + 1)
                - lgamma(l + 1)
                - lgamma(C_count)
            )
    return (
        1
        - probability_B_beats_A_count_data(C_count, C_exposure, A_count, A_exposure)
        - probability_B_beats_A_count_data(C_count, C_exposure, B_count, B_exposure)
        + total
    )
