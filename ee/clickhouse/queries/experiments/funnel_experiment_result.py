import dataclasses
from datetime import datetime
from math import exp, log
from typing import List, Optional, Tuple, Type

import scipy.special as sc
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels import ClickhouseFunnel
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


@dataclasses.dataclass
class Variant:
    name: str
    success_count: int
    failure_count: int


SIMULATION_COUNT = 100_000


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
        feature_flag: str,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
        funnel_class: Type[ClickhouseFunnel] = ClickhouseFunnel,
    ):

        breakdown_key = f"$feature/{feature_flag}"

        query_filter = filter.with_data(
            {
                "date_from": experiment_start_date,
                "date_to": experiment_end_date,
                "breakdown": breakdown_key,
                "breakdown_type": "event",
                "properties": [
                    {"key": breakdown_key, "value": ["control", "test"], "operator": "exact", "type": "event"}
                ],
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
        variants = []
        for result in funnel_results:
            total = sum([step["count"] for step in result])
            success = result[-1]["count"]
            failure = total - success
            breakdown_value = result[0]["breakdown_value"][0]

            variants.append(Variant(breakdown_value, success, failure))

        # Default variant names: control and test
        return sorted(variants, key=lambda variant: variant.name)

    @staticmethod
    def calculate_results(variants: List[Variant], priors: Tuple[int, int] = (1, 1)) -> float:
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
        if len(variants) > 2:
            raise ValidationError("Can't calculate A/B test results for more than 2 variants", code="too_much_data")

        if len(variants) < 2:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        prior_success, prior_failure = priors

        # calculation:
        # https://www.evanmiller.org/bayesian-ab-testing.html#binary_ab

        test_success = prior_success + variants[1].success_count
        test_failure = prior_failure + variants[1].failure_count

        control_success = prior_success + variants[0].success_count
        control_failure = prior_failure + variants[0].failure_count

        return probability_B_beats_A(control_success, control_failure, test_success, test_failure)


def probability_B_beats_A(A_success: int, A_failure: int, B_success: int, B_failure: int) -> float:
    total: float = 0
    for i in range(B_success):
        total += exp(
            sc.betaln(A_success + i, A_failure + B_failure)
            - log(B_failure + i)
            - sc.betaln(1 + i, B_failure)
            - sc.betaln(A_success, A_failure)
        )

    return total
