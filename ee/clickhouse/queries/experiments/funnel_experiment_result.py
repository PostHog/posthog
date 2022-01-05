import dataclasses
from datetime import datetime
from math import exp, lgamma, log
from typing import List, Optional, Tuple, Type

import scipy.special as sc
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels import ClickhouseFunnel
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


@dataclasses.dataclass
class Variant:
    name: str
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
        variants = self.get_variants(funnel_results)

        probability = self.calculate_results(variants)

        return {"funnel": funnel_results, "probability": probability, "filters": self.funnel._filter.to_dict()}

    def get_variants(self, funnel_results):
        control_variant = None
        test_variants = []
        for result in funnel_results:
            total = sum([step["count"] for step in result])
            success = result[-1]["count"]
            failure = total - success
            breakdown_value = result[0]["breakdown_value"][0]
            if breakdown_value == CONTROL_VARIANT_KEY:
                control_variant = Variant(name=breakdown_value, success_count=success, failure_count=failure)
            else:
                test_variants.append(Variant(breakdown_value, success, failure))

        return control_variant, test_variants

    @staticmethod
    def calculate_results(
        control_variant: Variant, test_variants: List[Variant], priors: Tuple[int, int] = (1, 1)
    ) -> List[float]:
        """
        Calculates probability that A is better than B. First variant is control, rest are test variants.
        
        Only supports 2 variants today

        For each variant, we create a Beta distribution of conversion rates, 
        where alpha (successes) = success count of variant + prior success
        beta (failures) = failure count + variant + prior failures

        The prior is information about the world we already know. For example, a stronger prior for failures implies
        you'd need extra evidence of successes to confirm that the variant is indeed better.

        By default, we choose a non-informative prior. That is, both success & failure are equally likely.
        
        """
        if len(test_variants) > 3:
            raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")

        if len(test_variants) < 1:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        prior_success, prior_failure = priors

        # calculation:
        # https://www.evanmiller.org/bayesian-ab-testing.html#binary_ab
        control_success = prior_success + control_variant.success_count
        control_failure = prior_failure + control_variant.failure_count

        success_and_failures = [
            (prior_success + test_variant.success_count, prior_failure + test_variant.failure_count)
            for test_variant in test_variants
        ]

        return calculate_probability_of_winning_for_each([(control_success, control_failure), *success_and_failures])


def calculate_probability_of_winning_for_each(variants: List[Tuple[int, int]]) -> List[float]:
    """
    Calculates the probability of winning for each variant.
    """
    if len(variants) == 2:
        # simple case
        probability = probability_B_beats_A(variants[0][0], variants[0][1], variants[1][0], variants[1][1])
        return [1 - probability, probability]

    elif len(variants) == 3:
        probability_third_wins = probability_C_beats_A_and_B(
            variants[0][0], variants[0][1], variants[1][0], variants[1][1], variants[2][0], variants[2][1]
        )
        probability_second_wins = probability_C_beats_A_and_B(
            variants[0][0], variants[0][1], variants[2][0], variants[2][1], variants[1][0], variants[1][1]
        )
        return [1 - probability_third_wins - probability_second_wins, probability_second_wins, probability_third_wins]

    elif len(variants) == 4:
        probability_second_wins = probability_D_beats_A_B_and_C(
            variants[0][0],
            variants[0][1],
            variants[2][0],
            variants[2][1],
            variants[3][0],
            variants[3][1],
            variants[1][0],
            variants[1][1],
        )
        probability_third_wins = probability_D_beats_A_B_and_C(
            variants[0][0],
            variants[0][1],
            variants[3][0],
            variants[3][1],
            variants[1][0],
            variants[1][1],
            variants[2][0],
            variants[2][1],
        )
        probability_fourth_wins = probability_D_beats_A_B_and_C(
            variants[0][0],
            variants[0][1],
            variants[1][0],
            variants[1][1],
            variants[2][0],
            variants[2][1],
            variants[3][0],
            variants[3][1],
        )
        return [
            1 - probability_second_wins - probability_third_wins - probability_fourth_wins,
            probability_second_wins,
            probability_third_wins,
            probability_fourth_wins,
        ]
    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")


def logbeta(a, b):
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def probability_B_beats_A(A_success: int, A_failure: int, B_success: int, B_failure: int) -> float:
    total: float = 0
    for i in range(B_success):
        total += exp(
            logbeta(A_success + i, A_failure + B_failure)
            - log(B_failure + i)
            - logbeta(1 + i, B_failure)
            - logbeta(A_success, A_failure)
        )

    return total


def probability_C_beats_A_and_B(
    A_success: int, A_failure: int, B_success: int, B_failure: int, C_success: int, C_failure: int
):

    total: float = 0
    for i in range(A_success):
        for j in range(B_success):
            total += exp(
                logbeta(C_success + i + j, C_failure + A_failure + B_failure)
                - log(A_failure + i)
                - log(B_failure + j)
                - logbeta(1 + i, A_failure)
                - logbeta(1 + j, B_failure)
                - logbeta(C_success, C_failure)
            )

    return (
        1
        - probability_B_beats_A(C_success, C_failure, A_success, A_failure)
        - probability_B_beats_A(C_success, C_failure, B_success, B_failure)
        + total
    )


def probability_D_beats_A_B_and_C(
    A_success: int,
    A_failure: int,
    B_success: int,
    B_failure: int,
    C_success: int,
    C_failure: int,
    D_success: int,
    D_failure: int,
):
    pass
