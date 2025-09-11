from datetime import datetime
from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.constants import INSIGHT_FUNNELS, INSIGHT_TRENDS
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

from ee.clickhouse.queries.experiments.funnel_experiment_result import ClickhouseFunnelExperimentResult
from ee.clickhouse.queries.experiments.trend_experiment_result import (
    ClickhouseTrendExperimentResult,
    uses_math_aggregation_by_user_or_property_value,
)


class ClickhouseSecondaryExperimentResult:
    """
    This class calculates secondary metric values for Experiments.
    It returns value of metric for each variant.

    We adjust the metric filter based on Experiment parameters.
    """

    def __init__(
        self,
        filter: Filter,
        team: Team,
        feature_flag: FeatureFlag,
        experiment_start_date: datetime,
        experiment_end_date: Optional[datetime] = None,
    ):
        self.variants = [variant["key"] for variant in feature_flag.variants]
        self.team = team
        self.feature_flag = feature_flag
        self.filter = filter
        self.experiment_start_date = experiment_start_date
        self.experiment_end_date = experiment_end_date

    def get_results(self):
        if self.filter.insight == INSIGHT_TRENDS:
            significance_results = ClickhouseTrendExperimentResult(
                self.filter, self.team, self.feature_flag, self.experiment_start_date, self.experiment_end_date
            ).get_results(validate=False)
            variants = self.get_trend_count_data_for_variants(significance_results["insight"])

        elif self.filter.insight == INSIGHT_FUNNELS:
            significance_results = ClickhouseFunnelExperimentResult(
                self.filter, self.team, self.feature_flag, self.experiment_start_date, self.experiment_end_date
            ).get_results(validate=False)
            variants = self.get_funnel_conversion_rate_for_variants(significance_results["insight"])

        else:
            raise ValidationError("Secondary metrics need to be funnel or trend insights")

        return {"result": variants, **significance_results}

    def get_funnel_conversion_rate_for_variants(self, insight_results) -> dict[str, float]:
        variants = {}
        for result in insight_results:
            total = result[0]["count"]
            success = result[-1]["count"]
            breakdown_value = result[0]["breakdown_value"][0]

            if breakdown_value in self.variants:
                variants[breakdown_value] = round(int(success) / int(total), 3)

        return variants

    def get_trend_count_data_for_variants(self, insight_results) -> dict[str, float]:
        # this assumes the Trend insight is Cumulative, unless using count per user
        variants = {}

        for result in insight_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]

            if uses_math_aggregation_by_user_or_property_value(self.filter):
                count = result["count"] / len(result.get("data", [0]))

            if breakdown_value in self.variants:
                variants[breakdown_value] = count

        return variants
