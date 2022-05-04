from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from math import exp, lgamma, log
from typing import List, Optional, Tuple, Type

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.experiments import (
    CONTROL_VARIANT_KEY,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.constants import ACTIONS, EVENTS, TRENDS_CUMULATIVE, ExperimentSignificanceCode
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

Probability = float

P_VALUE_SIGNIFICANCE_LEVEL = 0.05


@dataclass(frozen=True)
class Variant:
    key: str
    count: int
    exposure: float
    # count of total events exposed to variant
    absolute_exposure: int


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
                "display": TRENDS_CUMULATIVE,
                "date_from": experiment_start_date,
                "date_to": experiment_end_date,
                "breakdown": breakdown_key,
                "breakdown_type": "event",
                "properties": [{"key": breakdown_key, "value": variants, "operator": "exact", "type": "event"}],
                # :TRICKY: We don't use properties set on filters, instead using experiment variant options
            }
        )

        exposure_filter = filter.with_data(
            {
                "date_from": experiment_start_date,
                "date_to": experiment_end_date,
                "display": TRENDS_CUMULATIVE,
                ACTIONS: [],
                EVENTS: [
                    {
                        "id": "$feature_flag_called",
                        "name": "$feature_flag_called",
                        "order": 0,
                        "type": "events",
                        "math": "dau",
                    }
                ],
                "breakdown_type": "event",
                "breakdown": "$feature_flag_response",
                "properties": [
                    {"key": "$feature_flag_response", "value": variants, "operator": "exact", "type": "event"},
                    {"key": "$feature_flag", "value": [feature_flag.key], "operator": "exact", "type": "event"},
                ],
            }
        )

        self.query_filter = query_filter
        self.exposure_filter = exposure_filter
        self.team = team
        self.insight = trend_class()

    def get_results(self):
        insight_results = self.insight.run(self.query_filter, self.team)
        exposure_results = self.insight.run(self.exposure_filter, self.team,)
        control_variant, test_variants = self.get_variants(insight_results, exposure_results)

        probabilities = self.calculate_results(control_variant, test_variants)

        mapping = {
            variant.key: probability for variant, probability in zip([control_variant, *test_variants], probabilities)
        }

        significance_code, p_value = self.are_results_significant(control_variant, test_variants, probabilities)

        return {
            "insight": insight_results,
            "probability": mapping,
            "significant": significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            "filters": self.query_filter.to_dict(),
            "significance_code": significance_code,
            "p_value": p_value,
            "variants": [asdict(variant) for variant in [control_variant, *test_variants]],
        }

    def get_variants(self, insight_results, exposure_results):
        # this assumes the Trend insight is Cumulative
        control_variant = None
        test_variants = []
        exposure_counts = {}
        exposure_ratios = {}

        for result in exposure_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]
            exposure_counts[breakdown_value] = count

        control_exposure = exposure_counts.get(CONTROL_VARIANT_KEY, 0)

        if control_exposure != 0:
            for key, count in exposure_counts.items():
                exposure_ratios[key] = count / control_exposure

        for result in insight_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]
            if breakdown_value == CONTROL_VARIANT_KEY:
                # count exposure value is always 1, the baseline
                control_variant = Variant(
                    key=breakdown_value,
                    count=int(count),
                    exposure=1,
                    absolute_exposure=exposure_counts.get(breakdown_value, 1),
                )
            else:
                test_variants.append(
                    Variant(
                        breakdown_value,
                        int(count),
                        exposure_ratios.get(breakdown_value, 1),
                        exposure_counts.get(breakdown_value, 1),
                    )
                )

        return control_variant, test_variants

    @staticmethod
    def calculate_results(control_variant: Variant, test_variants: List[Variant]) -> List[Probability]:
        """
        Calculates probability that A is better than B. First variant is control, rest are test variants.

        Supports maximum 4 variants today

        For each variant, we create a Gamma distribution of arrival rates,
        where alpha (shape parameter) = count of variant + 1
        beta (exposure parameter) = 1
        """
        if not control_variant:
            raise ValidationError("No control variant data found", code="no_data")

        if len(test_variants) > 2:
            raise ValidationError("Can't calculate A/B test results for more than 3 variants", code="too_much_data")

        if len(test_variants) < 1:
            raise ValidationError("Can't calculate A/B test results for less than 2 variants", code="no_data")

        return calculate_probability_of_winning_for_each([control_variant, *test_variants])

    @staticmethod
    def are_results_significant(
        control_variant: Variant, test_variants: List[Variant], probabilities: List[Probability]
    ) -> Tuple[ExperimentSignificanceCode, Probability]:
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


def simulate_winning_variant_for_arrival_rates(target_variant: Variant, variants: List[Variant]) -> float:
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
        return [max(0, 1 - probability), probability]

    elif len(variants) == 3:
        probability_third_wins = simulate_winning_variant_for_arrival_rates(variants[2], [variants[0], variants[1]])
        probability_second_wins = simulate_winning_variant_for_arrival_rates(variants[1], [variants[0], variants[2]])
        return [
            max(0, 1 - probability_third_wins - probability_second_wins),
            probability_second_wins,
            probability_third_wins,
        ]

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
            max(0, 1 - probability_fourth_wins - probability_third_wins - probability_second_wins),
            probability_second_wins,
            probability_third_wins,
            probability_fourth_wins,
        ]
    else:
        raise ValidationError("Can't calculate A/B test results for more than 4 variants", code="too_much_data")


@lru_cache(maxsize=100_000)
def combinationln(n: int, k: int) -> float:
    """
    Returns the log of the binomial coefficient.
    """
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


def intermediate_poisson_term(count: int, iterator: int, relative_exposure: float):
    return exp(
        combinationln(count, iterator)
        + iterator * log(relative_exposure)
        + (count - iterator) * log(1 - relative_exposure)
    )


def poisson_p_value(control_count, control_exposure, test_count, test_exposure):
    """
    Calculates the p-value of the A/B test.
    Calculations from: https://www.evanmiller.org/statistical-formulas-for-programmers.html#count_test
    """
    relative_exposure = test_exposure / (control_exposure + test_exposure)
    total_count = control_count + test_count

    low_p_value = 0.0
    high_p_value = 0.0

    for i in range(test_count + 1):
        low_p_value += intermediate_poisson_term(total_count, i, relative_exposure)

    for i in range(test_count, total_count + 1):
        high_p_value += intermediate_poisson_term(total_count, i, relative_exposure)

    return min(1, 2 * min(low_p_value, high_p_value))


def calculate_p_value(control_variant: Variant, test_variants: List[Variant]) -> Probability:
    best_test_variant = max(test_variants, key=lambda variant: variant.count)

    return poisson_p_value(
        control_variant.count, control_variant.exposure, best_test_variant.count, best_test_variant.exposure
    )
