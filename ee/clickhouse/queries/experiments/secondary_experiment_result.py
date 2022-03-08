from datetime import datetime
from typing import Dict, Optional

from rest_framework.exceptions import ValidationError

from ee.clickhouse.queries.funnels import ClickhouseFunnel
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from posthog.constants import INSIGHT_FUNNELS, INSIGHT_TRENDS, TRENDS_CUMULATIVE
from posthog.models.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


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

        self.team = team
        if query_filter.insight == INSIGHT_TRENDS:
            query_filter = query_filter.with_data({"display": TRENDS_CUMULATIVE})

        self.query_filter = query_filter

    def get_results(self):

        if self.query_filter.insight == INSIGHT_TRENDS:
            trend_results = ClickhouseTrends().run(self.query_filter, self.team)
            variants = self.get_trend_count_data_for_variants(trend_results)

        elif self.query_filter.insight == INSIGHT_FUNNELS:
            funnel_results = ClickhouseFunnel(self.query_filter, self.team).run()
            variants = self.get_funnel_conversion_rate_for_variants(funnel_results)

        else:
            raise ValidationError("Secondary metrics need to be funnel or trend insights")

        return {"result": variants}

    def get_funnel_conversion_rate_for_variants(self, insight_results) -> Dict[str, float]:
        variants = {}
        for result in insight_results:
            total = result[0]["count"]
            success = result[-1]["count"]
            breakdown_value = result[0]["breakdown_value"][0]
            variants[breakdown_value] = round(int(success) / int(total), 3)

        return variants

    def get_trend_count_data_for_variants(self, insight_results) -> Dict[str, float]:
        # this assumes the Trend insight is Cumulative
        variants = {}

        for result in insight_results:
            count = result["count"]
            breakdown_value = result["breakdown_value"]
            variants[breakdown_value] = count

        return variants
