from posthog.hogql import ast
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from .insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.schema import (
    ExperimentFunnelQuery,
    ExperimentFunnelQueryResponse,
    ExperimentVariantFunnelResult,
    FunnelsQuery,
    InsightDateRange,
    BreakdownFilter,
)
from typing import Any
from zoneinfo import ZoneInfo


class ExperimentFunnelQueryRunner(QueryRunner):
    query: ExperimentFunnelQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.prepared_funnel_query = self._prepare_funnel_query()
        self.query_runner = FunnelsQueryRunner(
            query=self.prepared_funnel_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def calculate(self) -> ExperimentFunnelQueryResponse:
        response = self.query_runner.calculate()
        results = self._process_results(response.results)
        return ExperimentFunnelQueryResponse(insight="FUNNELS", results=results)

    def _prepare_funnel_query(self) -> FunnelsQuery:
        """
        This method takes the raw funnel query and adapts it
        for the needs of experiment analysis:

        1. Set the date range to match the experiment's duration, using the project's timezone.
        2. Configure the breakdown to use the feature flag key, which allows us
           to separate results for different experiment variants.
        """
        # Clone the source query
        prepared_funnel_query = FunnelsQuery(**self.query.source.model_dump())

        # Set the date range to match the experiment's duration, using the project's timezone
        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        prepared_funnel_query.dateRange = InsightDateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

        # Configure the breakdown to use the feature flag key
        prepared_funnel_query.breakdownFilter = BreakdownFilter(
            breakdown=f"$feature/{self.feature_flag.key}",
            breakdown_type="event",
        )

        return prepared_funnel_query

    def _process_results(self, funnels_results: list[list[dict[str, Any]]]) -> dict[str, ExperimentVariantFunnelResult]:
        variants = self.feature_flag.variants
        processed_results = {
            variant["key"]: ExperimentVariantFunnelResult(success_count=0, failure_count=0) for variant in variants
        }

        for result in funnels_results:
            first_step = result[0]
            last_step = result[-1]
            variant = first_step.get("breakdown_value")
            variant_str = variant[0] if isinstance(variant, list) else str(variant)
            if variant_str in processed_results:
                total_count = first_step.get("count", 0)
                success_count = last_step.get("count", 0) if len(result) > 1 else 0
                processed_results[variant_str].success_count = success_count
                processed_results[variant_str].failure_count = total_count - success_count

        return processed_results

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.source.kind} to query")
