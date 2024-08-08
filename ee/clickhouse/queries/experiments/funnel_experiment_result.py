from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Optional
from zoneinfo import ZoneInfo

from numpy.random import default_rng
from rest_framework.exceptions import ValidationError
import scipy.stats as stats
from sentry_sdk import capture_exception

from ee.clickhouse.queries.experiments import (
    CONTROL_VARIANT_KEY,
    FF_DISTRIBUTION_THRESHOLD,
    MIN_PROBABILITY_FOR_SIGNIFICANCE,
)
from posthog.constants import ExperimentSignificanceCode, ExperimentNoResultsErrorKeys
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.funnels import ClickhouseFunnel

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

    Currently, we support a maximum of 10 feature flag values: control and 9 test variants

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
        funnel_class: type[ClickhouseFunnel] = ClickhouseFunnel,
    ):
        breakdown_key = f"$feature/{feature_flag.key}"
        self.variants = [variant["key"] for variant in feature_flag.variants]

        # our filters assume that the given time ranges are in the project timezone.
        # while start and end date are in UTC.
        # so we need to convert them to the project timezone
        if team.timezone:
            start_date_in_project_timezone = experiment_start_date.astimezone(ZoneInfo(team.timezone))
            end_date_in_project_timezone = (
                experiment_end_date.astimezone(ZoneInfo(team.timezone)) if experiment_end_date else None
            )

        query_filter = filter.shallow_clone(
            {
                "date_from": start_date_in_project_timezone,
                "date_to": end_date_in_project_timezone,
                "explicit_date": True,
                "breakdown": breakdown_key,
                "breakdown_type": "event",
                "properties": [],
                # :TRICKY: We don't use properties set on filters, as these
                # correspond to feature flag properties, not the funnel properties.
                # This is also why we simplify only right now so new properties (from test account filters)
                # are added appropriately.
                "is_simplified": False,
            }
        )
        self.funnel = funnel_class(query_filter, team)

    def get_results(self, validate: bool = True):
        funnel_results = self.funnel.run()

        basic_result_props = {
            # TODO: check if this can error out or not?, i.e. results don't have 0 index?
            "insight": [result for result in funnel_results if result[0]["breakdown_value"][0] in self.variants],
            "filters": self.funnel._filter.to_dict(),
        }

        try:
            validate_event_variants(funnel_results, self.variants)

            filtered_results = [result for result in funnel_results if result[0]["breakdown_value"][0] in self.variants]

            control_variant, test_variants = self.get_variants(filtered_results)

            probabilities = self.calculate_results(control_variant, test_variants)

            mapping = {
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            }

            significance_code, loss = self.are_results_significant(control_variant, test_variants, probabilities)

            credible_intervals = calculate_credible_intervals([control_variant, *test_variants])
        except ValidationError:
            if validate:
                raise
            else:
                return basic_result_props

        return {
            **basic_result_props,
            "probability": mapping,
            "significant": significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            "significance_code": significance_code,
            "expected_loss": loss,
            "variants": [asdict(variant) for variant in [control_variant, *test_variants]],
            "credible_intervals": credible_intervals,
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
                control_variant = Variant(
                    key=breakdown_value,
                    success_count=int(success),
                    failure_count=int(failure),
                )
            else:
                test_variants.append(Variant(breakdown_value, int(success), int(failure)))

        return control_variant, test_variants

    @staticmethod
    def calculate_results(
        control_variant: Variant,
        test_variants: list[Variant],
        priors: tuple[int, int] = (1, 1),
    ) -> list[Probability]:
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

        if len(test_variants) >= 10:
            raise ValidationError(
                "Can't calculate A/B test results for more than 10 variants",
                code="too_much_data",
            )

        if len(test_variants) < 1:
            raise ValidationError(
                "Can't calculate A/B test results for less than 2 variants",
                code="no_data",
            )

        return calculate_probability_of_winning_for_each([control_variant, *test_variants])

    @staticmethod
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


def calculate_probability_of_winning_for_each(variants: list[Variant]) -> list[Probability]:
    """
    Calculates the probability of winning for each variant.
    """
    if len(variants) > 10:
        raise ValidationError(
            "Can't calculate A/B test results for more than 10 variants",
            code="too_much_data",
        )

    probabilities = []
    # simulate winning for each test variant
    for index, variant in enumerate(variants):
        probabilities.append(simulate_winning_variant_for_conversion(variant, variants[:index] + variants[index + 1 :]))

    total_test_probabilities = sum(probabilities[1:])

    return [max(0, 1 - total_test_probabilities), *probabilities[1:]]


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


def validate_event_variants(funnel_results, variants):
    errors = {
        ExperimentNoResultsErrorKeys.NO_EVENTS: True,
        ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
        ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
        ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
    }

    if not funnel_results or not funnel_results[0]:
        raise ValidationError(code="no-results", detail=json.dumps(errors))

    errors[ExperimentNoResultsErrorKeys.NO_EVENTS] = False

    # Funnels: the first step must be present for *any* results to show up
    eventsWithOrderZero = []
    for eventArr in funnel_results:
        for event in eventArr:
            if event.get("order") == 0:
                eventsWithOrderZero.append(event)

    # Check if "control" is present
    for event in eventsWithOrderZero:
        event_variant = event.get("breakdown_value")[0]
        if event_variant == "control":
            errors[ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT] = False
            errors[ExperimentNoResultsErrorKeys.NO_FLAG_INFO] = False
            break

    # Check if at least one of the test variants is present
    test_variants = [variant for variant in variants if variant != "control"]
    for event in eventsWithOrderZero:
        event_variant = event.get("breakdown_value")[0]
        if event_variant in test_variants:
            errors[ExperimentNoResultsErrorKeys.NO_TEST_VARIANT] = False
            errors[ExperimentNoResultsErrorKeys.NO_FLAG_INFO] = False
            break

    has_errors = any(errors.values())
    if has_errors:
        raise ValidationError(detail=json.dumps(errors))
