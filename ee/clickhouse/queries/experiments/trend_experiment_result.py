import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentSignificanceCode

from posthog.constants import (
    ACTIONS,
    EVENTS,
    TRENDS_CUMULATIVE,
    TRENDS_LINEAR,
    UNIQUE_USERS,
    ExperimentNoResultsErrorKeys,
)
from posthog.hogql_queries.experiments.trends_statistics import (
    are_results_significant,
    calculate_credible_intervals,
    calculate_probabilities,
)
from posthog.models.experiment import ExperimentHoldout
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.trends.trends import Trends
from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS

from ee.clickhouse.queries.experiments import CONTROL_VARIANT_KEY

Probability = float


@dataclass(frozen=True)
class Variant:
    key: str
    count: int
    # a fractional value, representing the proportion of the variant's exposure events relative to *control* exposure events
    # default: the proportion of unique users relative to the *control* unique users
    exposure: float
    # count of total exposure events exposed for a variant
    # default: total number of unique users exposed to the variant (via "Feature flag called" event)
    absolute_exposure: int


def uses_math_aggregation_by_user_or_property_value(filter: Filter):
    # sync with frontend: https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/experiments/experimentLogic.tsx#L662
    # the selector experimentCountPerUserMath

    entities = filter.entities
    math_keys = ALL_SUPPORTED_MATH_FUNCTIONS

    # 'sum' doesn't need special handling, we can have custom exposure for sum filters
    if "sum" in math_keys:
        math_keys.remove("sum")

    return any(entity.math in math_keys for entity in entities)


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
        trend_class: type[Trends] = Trends,
        custom_exposure_filter: Optional[Filter] = None,
        holdout: Optional[ExperimentHoldout] = None,
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

        uses_math_aggregation = uses_math_aggregation_by_user_or_property_value(filter)

        # Keep in sync with https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/experiments/ExperimentView/components.tsx#L91
        query_filter = filter.shallow_clone(
            {
                "display": TRENDS_CUMULATIVE if not uses_math_aggregation else TRENDS_LINEAR,
                "date_from": start_date_in_project_timezone,
                "date_to": end_date_in_project_timezone,
                "explicit_date": True,
                "breakdown": breakdown_key,
                "breakdown_type": "event",
                "properties": [
                    {
                        "key": breakdown_key,
                        "value": self.variants,
                        "operator": "exact",
                        "type": "event",
                    }
                ],
                # :TRICKY: We don't use properties set on filters, instead using experiment variant options
                # :TRICKY: We don't use properties set on filters, as these
                # correspond to feature flag properties, not the trend properties.
                # This is also why we simplify only right now so new properties (from test account filters)
                # are added appropriately.
                "is_simplified": False,
            }
        )

        if uses_math_aggregation:
            # A trend experiment can have only one metric, so take the first one to calculate exposure
            # We copy the entity to avoid mutating the original filter
            entity = query_filter.shallow_clone({}).entities[0]
            # :TRICKY: With count per user aggregation, our exposure filter is implicit:
            # (1) We calculate the unique users for this event -> this is the exposure
            # (2) We calculate the total count of this event -> this is the trend goal metric / arrival rate for probability calculation
            # TODO: When we support group aggregation per user, change this.
            entity.math = None
            exposure_entity = entity.to_dict()
            entity.math = UNIQUE_USERS
            count_entity = entity.to_dict()

            target_entities = [exposure_entity, count_entity]
            query_filter_actions = []
            query_filter_events = []
            if entity.type == ACTIONS:
                query_filter_actions = target_entities
            else:
                query_filter_events = target_entities

            # two entities in exposure, one for count, the other for result
            exposure_filter = query_filter.shallow_clone(
                {
                    "display": TRENDS_CUMULATIVE,
                    ACTIONS: query_filter_actions,
                    EVENTS: query_filter_events,
                }
            )

        else:
            # TODO: Exposure doesn't need to compute daily values, so instead of
            # using TRENDS_CUMULATIVE, we can use TRENDS_TABLE to just get the total.
            if custom_exposure_filter:
                exposure_filter = custom_exposure_filter.shallow_clone(
                    {
                        "display": TRENDS_CUMULATIVE,
                        "date_from": experiment_start_date,
                        "date_to": experiment_end_date,
                        "explicit_date": True,
                        "breakdown": breakdown_key,
                        "breakdown_type": "event",
                        "properties": [
                            {
                                "key": breakdown_key,
                                "value": self.variants,
                                "operator": "exact",
                                "type": "event",
                            }
                        ],
                        # :TRICKY: We don't use properties set on filters, as these
                        # correspond to feature flag properties, not the trend-exposure properties.
                        # This is also why we simplify only right now so new properties (from test account filters)
                        # are added appropriately.
                        "is_simplified": False,
                    }
                )
            else:
                exposure_filter = filter.shallow_clone(
                    {
                        "display": TRENDS_CUMULATIVE,
                        "date_from": experiment_start_date,
                        "date_to": experiment_end_date,
                        "explicit_date": True,
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
                            {
                                "key": "$feature_flag_response",
                                "value": self.variants,
                                "operator": "exact",
                                "type": "event",
                            },
                            {
                                "key": "$feature_flag",
                                "value": [feature_flag.key],
                                "operator": "exact",
                                "type": "event",
                            },
                        ],
                        # :TRICKY: We don't use properties set on filters, as these
                        # correspond to feature flag properties, not the trend-exposure properties.
                        # This is also why we simplify only right now so new properties (from test account filters)
                        # are added appropriately.
                        "is_simplified": False,
                    }
                )

        self.query_filter = query_filter
        self.exposure_filter = exposure_filter
        self.team = team
        self.insight = trend_class()

    def get_results(self, validate: bool = True):
        insight_results = self.insight.run(self.query_filter, self.team)
        exposure_results = self.insight.run(self.exposure_filter, self.team)

        basic_result_props = {
            "insight": insight_results,
            "filters": self.query_filter.to_dict(),
            "exposure_filters": self.exposure_filter.to_dict(),
        }

        try:
            validate_event_variants(insight_results, self.variants)

            control_variant, test_variants = self.get_variants(insight_results, exposure_results)

            probabilities = calculate_probabilities(control_variant, test_variants)

            mapping = {
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            }

            significance_code, p_value = are_results_significant(control_variant, test_variants, probabilities)

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
            "p_value": p_value,
            "variants": [asdict(variant) for variant in [control_variant, *test_variants]],
            "credible_intervals": credible_intervals,
        }

    def get_variants(self, insight_results, exposure_results):
        # this assumes the Trend insight is Cumulative
        control_variant = None
        test_variants = []
        exposure_counts = {}
        exposure_ratios = {}

        # :TRICKY: With count per user aggregation, our exposure filter is implicit:
        # (1) We calculate the unique users for this event -> this is the exposure
        # (2) We calculate the total count of this event -> this is the trend goal metric / arrival rate for probability calculation
        # TODO: When we support group aggregation per user, change this.
        if uses_math_aggregation_by_user_or_property_value(self.query_filter):
            filtered_exposure_results = [
                result for result in exposure_results if result["action"]["math"] == UNIQUE_USERS
            ]
            filtered_insight_results = [
                result for result in exposure_results if result["action"]["math"] != UNIQUE_USERS
            ]
        else:
            filtered_exposure_results = exposure_results
            filtered_insight_results = insight_results

        for result in filtered_exposure_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]
            exposure_counts[breakdown_value] = count

        control_exposure = exposure_counts.get(CONTROL_VARIANT_KEY, 0)

        if control_exposure != 0:
            for key, count in exposure_counts.items():
                exposure_ratios[key] = count / control_exposure

        for result in filtered_insight_results:
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


def validate_event_variants(trend_results, variants):
    errors = {
        ExperimentNoResultsErrorKeys.NO_EVENTS: True,
        ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
        ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
        ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
    }

    if not trend_results or not trend_results[0]:
        raise ValidationError(code="no-results", detail=json.dumps(errors))

    errors[ExperimentNoResultsErrorKeys.NO_EVENTS] = False

    # Check if "control" is present
    for event in trend_results:
        event_variant = event.get("breakdown_value")
        if event_variant == "control":
            errors[ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT] = False
            errors[ExperimentNoResultsErrorKeys.NO_FLAG_INFO] = False
            break

    # Check if at least one of the test variants is present
    test_variants = [variant for variant in variants if variant != "control"]
    for event in trend_results:
        event_variant = event.get("breakdown_value")
        if event_variant in test_variants:
            errors[ExperimentNoResultsErrorKeys.NO_TEST_VARIANT] = False
            errors[ExperimentNoResultsErrorKeys.NO_FLAG_INFO] = False
            break

    has_errors = any(errors.values())
    if has_errors:
        raise ValidationError(detail=json.dumps(errors))
