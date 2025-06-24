import json
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql import ast
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.hogql_queries.experiments.funnels_statistics_v2 import (
    are_results_significant_v2,
    calculate_credible_intervals_v2,
    calculate_probabilities_v2,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from ..insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.schema import (
    CachedExperimentFunnelsQueryResponse,
    ExperimentFunnelsQuery,
    ExperimentFunnelsQueryResponse,
    ExperimentSignificanceCode,
    ExperimentVariantFunnelsBaseStats,
    FunnelLayout,
    FunnelsFilter,
    FunnelsQuery,
    FunnelsQueryResponse,
    DateRange,
    BreakdownFilter,
)
from typing import Optional, Any, cast
from zoneinfo import ZoneInfo
from rest_framework.exceptions import ValidationError
from datetime import datetime, timedelta, UTC


class ExperimentFunnelsQueryRunner(QueryRunner):
    query: ExperimentFunnelsQuery
    response: ExperimentFunnelsQueryResponse
    cached_response: CachedExperimentFunnelsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.prepared_funnels_query = self._prepare_funnel_query()
        self.funnels_query_runner = FunnelsQueryRunner(
            query=self.prepared_funnels_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def calculate(self) -> ExperimentFunnelsQueryResponse:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            query_type="ExperimentFunnelsQuery",
            experiment_id=str(self.experiment.id),
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
        )

        funnels_result = self.funnels_query_runner.calculate()

        self._validate_event_variants(funnels_result)

        try:
            # Filter results to only include valid variants in the first step
            funnels_result.results = [
                result for result in funnels_result.results if result[0]["breakdown_value"][0] in self.variants
            ]

            # Statistical analysis
            control_variant, test_variants = self._get_variants_with_base_stats(funnels_result)
            probabilities = calculate_probabilities_v2(control_variant, test_variants)
            significance_code, loss = are_results_significant_v2(control_variant, test_variants, probabilities)
            credible_intervals = calculate_credible_intervals_v2([control_variant, *test_variants])
        except Exception as e:
            raise ValueError(f"Error calculating experiment funnel results: {str(e)}") from e

        return ExperimentFunnelsQueryResponse(
            kind="ExperimentFunnelsQuery",
            funnels_query=self.prepared_funnels_query,
            insight=funnels_result.results,
            variants=[variant.model_dump() for variant in [control_variant, *test_variants]],
            probability={
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            },
            significant=significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            significance_code=significance_code,
            stats_version=2,
            expected_loss=loss,
            credible_intervals=credible_intervals,
        )

    def _prepare_funnel_query(self) -> FunnelsQuery:
        """
        This method takes the raw funnel query and adapts it
        for the needs of experiment analysis:

        1. Set the date range to match the experiment's duration, using the project's timezone.
        2. Configure the breakdown to use the feature flag key, which allows us
           to separate results for different experiment variants.
        """
        # Clone the funnels query
        prepared_funnels_query = FunnelsQuery(**self.query.funnels_query.model_dump())

        # Set the date range to match the experiment's duration, using the project's timezone
        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        prepared_funnels_query.dateRange = DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

        # Configure the breakdown to use the feature flag key
        prepared_funnels_query.breakdownFilter = BreakdownFilter(
            breakdown=f"$feature/{self.feature_flag.key}",
            breakdown_type="event",
        )

        # Set the layout to vertical
        if prepared_funnels_query.funnelsFilter is None:
            prepared_funnels_query.funnelsFilter = FunnelsFilter()
        prepared_funnels_query.funnelsFilter.layout = FunnelLayout.VERTICAL

        return prepared_funnels_query

    def _get_variants_with_base_stats(
        self, funnels_result: FunnelsQueryResponse
    ) -> tuple[ExperimentVariantFunnelsBaseStats, list[ExperimentVariantFunnelsBaseStats]]:
        control_variant: Optional[ExperimentVariantFunnelsBaseStats] = None
        test_variants = []

        for result in funnels_result.results:
            result_dict = cast(list[dict[str, Any]], result)
            first_step = result_dict[0]
            last_step = result_dict[-1]

            total = first_step.get("count", 0)
            success = last_step.get("count", 0) if len(result_dict) > 1 else 0
            failure = total - success

            breakdown_value = cast(list[str], first_step["breakdown_value"])[0]

            if breakdown_value == CONTROL_VARIANT_KEY:
                control_variant = ExperimentVariantFunnelsBaseStats(
                    key=breakdown_value,
                    success_count=int(success),
                    failure_count=int(failure),
                )
            else:
                test_variants.append(
                    ExperimentVariantFunnelsBaseStats(
                        key=breakdown_value, success_count=int(success), failure_count=int(failure)
                    )
                )

        if control_variant is None:
            raise ValueError("Control variant not found in count results")

        return control_variant, test_variants

    def _validate_event_variants(self, funnels_result: FunnelsQueryResponse):
        errors = {
            ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
            ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
        }

        if not funnels_result.results or not funnels_result.results:
            raise ValidationError(code="no-results", detail=json.dumps(errors))

        # Funnels: the first step must be present for *any* results to show up
        eventsWithOrderZero = []
        for eventArr in funnels_result.results:
            for event in eventArr:
                event_dict = cast(dict[str, Any], event)
                if event_dict.get("order") == 0:
                    eventsWithOrderZero.append(event_dict)

        # Check if "control" is present
        for event in eventsWithOrderZero:
            event_variant = event.get("breakdown_value", [None])[0]
            if event_variant == "control":
                errors[ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT] = False
                break

        # Check if at least one of the test variants is present
        test_variants = [variant for variant in self.variants if variant != "control"]
        for event in eventsWithOrderZero:
            event_variant = event.get("breakdown_value", [None])[0]
            if event_variant in test_variants:
                errors[ExperimentNoResultsErrorKeys.NO_TEST_VARIANT] = False
                break

        has_errors = any(errors.values())
        if has_errors:
            raise ValidationError(detail=json.dumps(errors))

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.funnels_query.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
