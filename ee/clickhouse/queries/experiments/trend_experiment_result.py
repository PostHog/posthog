import dataclasses
from datetime import datetime
from math import exp, log
from typing import List, Optional, Type

import scipy.special as sc
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


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
        feature_flag: str,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
        trend_class: Type[ClickhouseTrends] = ClickhouseTrends,
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
        self.query_filter = query_filter
        self.team = team
        self.insight = trend_class()

    def get_results(self):
        insight_results = self.insight.run(self.query_filter, self.team)
        variants = self.get_variants(insight_results)

        probability = self.calculate_results(variants)

        return {"insight": insight_results, "probability": probability, "filters": self.query_filter.to_dict()}

    def get_variants(self, insight_results):
        # this assumes the Trend insight is Cumulative
        variants = []
        for result in insight_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]

            variants.append(Variant(breakdown_value, int(count)))

        # Default variant names: control and test
        return sorted(variants, key=lambda variant: variant.name)

    @staticmethod
    def calculate_results(variants: List[Variant]) -> float:
        """
        Calculates probability that A is better than B. First variant is control, rest are test variants.

        Only supports 2 variants today
        """
        if len(variants) > 2:
            raise ValidationError("Can't calculate A/B test results for more than 2 variants", code="too_much_data")

        if len(variants) < 2:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        # second calculation:
        # https://www.evanmiller.org/bayesian-ab-testing.html#binary_ab

        test_count = 1 + variants[1].count
        control_count = 1 + variants[0].count

        test_exposure = 1  # by default, all variants exposed for same duration
        control_exposure = 1

        return probability_B_beats_A_count_data(control_count, control_exposure, test_count, test_exposure)


def probability_B_beats_A_count_data(A_count: int, A_exposure: int, B_count: int, B_exposure: int) -> float:
    total: float = 0
    for i in range(B_count - 1):
        total += exp(
            i * log(B_exposure)
            + A_count * log(A_exposure)
            - (i + A_count) * log(B_exposure + A_exposure)
            - log(i + A_count)
            - sc.betaln(i + 1, A_count)
        )

    return total
