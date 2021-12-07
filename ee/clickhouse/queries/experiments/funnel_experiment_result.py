import dataclasses
from datetime import datetime
from typing import List, Optional, Tuple, Type

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels import ClickhouseFunnel, funnel
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


@dataclasses.dataclass
class Variant:
    name: str
    success_count: int
    failure_count: int


SIMULATION_COUNT = 100_000


class ClickhouseFunnelExperimentResult:
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
                # don't rely on properties used to set filters, taken over by $feature/X event properties
                # instead, filter by prop names we expect to see: the variant values
            }
        )
        self.funnel = funnel_class(query_filter, team)

    def get_results(self):
        funnel_results = self.funnel.run()
        variants = self.get_variants(funnel_results)

        probability = self.calculate_results(variants)

        return {"funnel": funnel_results, "probability": probability}

    def get_variants(self, funnel_results):
        variants = []
        for result in funnel_results:
            total = sum([step["count"] for step in result])
            success = result[-1]["count"]
            failure = total - success
            breakdown_value = result[0]["breakdown_value"][0]

            variants.append(Variant(breakdown_value, success, failure))

        # Default variant names: control and test
        return sorted(variants, key=lambda variant: variant.name, reverse=True)

    @staticmethod
    def calculate_results(
        variants: List[Variant], priors: Tuple[int, int] = (1, 1), simulations: int = SIMULATION_COUNT
    ):
        # Calculates probability that A is better than B
        if len(variants) > 2:
            raise ValidationError("Can't calculate A/B test results for more than 2 variants")

        if len(variants) < 2:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants")

        prior_success, prior_failure = priors

        random_sampler = default_rng()
        variant_samples = []
        for variant in variants:
            # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
            # and beta = prior_failure + variant_failure
            samples = random_sampler.beta(
                variant.success_count + prior_success, variant.failure_count + prior_failure, simulations
            )
            # print(samples)
            variant_samples.append(samples)

        probability = sum([int(sample_a > sample_b) for (sample_a, sample_b) in zip(*variant_samples)]) / simulations

        # histogram_values = [ sample_a / sample_b for (sample_a, sample_b) in zip(*variant_samples)]

        return probability
