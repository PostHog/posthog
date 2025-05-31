from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Optional
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.hogql_queries.experiments.funnels_statistics import (
    are_results_significant,
    calculate_credible_intervals,
    calculate_probabilities,
)
from posthog.models.experiment import ExperimentHoldout
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.funnels import ClickhouseFunnel
from posthog.schema import ExperimentSignificanceCode

Probability = float


@dataclass(frozen=True)
class Variant:
    key: str
    success_count: int
    failure_count: int


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

    Then, we calculate how many times a sample from `test` variant is higher than a sample from the `control` variant. This becomes the
    probability.
    """

    def __init__(
        self,
        filter: Filter,
        team: Team,
        feature_flag: FeatureFlag,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
        holdout: Optional[ExperimentHoldout] = None,
        funnel_class: type[ClickhouseFunnel] = ClickhouseFunnel,
    ):
        breakdown_key = f"$feature/{feature_flag.key}"
        self.variants = [variant["key"] for variant in feature_flag.variants]
        if holdout:
            self.variants.append(f"holdout-{holdout.id}")

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

            probabilities = calculate_probabilities(control_variant, test_variants)

            mapping = {
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            }

            significance_code, loss = are_results_significant(control_variant, test_variants, probabilities)

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
