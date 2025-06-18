import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql import ast
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import (
    are_results_significant_v2_continuous,
    calculate_credible_intervals_v2_continuous,
    calculate_probabilities_v2_continuous,
)
from posthog.hogql_queries.experiments.trends_statistics_v2_count import (
    are_results_significant_v2_count,
    calculate_credible_intervals_v2_count,
    calculate_probabilities_v2_count,
)
from posthog.hogql_queries.experiments.types import ExperimentMetricType
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models.experiment import Experiment
from posthog.queries.trends.util import ALL_SUPPORTED_MATH_FUNCTIONS
from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    CachedExperimentTrendsQueryResponse,
    ChartDisplayType,
    DataWarehouseNode,
    DataWarehousePropertyFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    ExperimentVariantTrendsBaseStats,
    PropertyMathType,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
    TrendsQueryResponse,
)


class ExperimentTrendsQueryRunner(QueryRunner):
    query: ExperimentTrendsQuery
    response: ExperimentTrendsQueryResponse
    cached_response: CachedExperimentTrendsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")
        self.breakdown_key = f"$feature/{self.feature_flag.key}"

        self._fix_math_aggregation()

        self.prepared_count_query = self._prepare_count_query()
        self.prepared_exposure_query = self._prepare_exposure_query()

        self.count_query_runner = TrendsQueryRunner(
            query=self.prepared_count_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )
        self.exposure_query_runner = TrendsQueryRunner(
            query=self.prepared_exposure_query, team=self.team, timings=self.timings, limit_context=self.limit_context
        )

    def _uses_math_aggregation_by_user_or_property_value(self, query: TrendsQuery):
        math_keys = ALL_SUPPORTED_MATH_FUNCTIONS
        # "sum" doesn't need special handling, we *can* have custom exposure for sum filters
        if "sum" in math_keys:
            math_keys.remove("sum")
        return any(entity.math in math_keys for entity in query.series)

    def _fix_math_aggregation(self):
        """
        Switch unsupported math aggregations to SUM
        """
        uses_math_aggregation = self._uses_math_aggregation_by_user_or_property_value(self.query.count_query)
        if uses_math_aggregation:
            self.query.count_query.series[0].math = PropertyMathType.SUM

    def _get_date_range(self) -> DateRange:
        """
        Returns an DateRange object based on the experiment's start and end dates,
        adjusted for the team's timezone if applicable.
        """
        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        return DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    def _get_event_breakdown_filter(self) -> BreakdownFilter:
        return BreakdownFilter(
            breakdown=self.breakdown_key,
            breakdown_type="event",
        )

    def _get_data_warehouse_breakdown_filter(self) -> BreakdownFilter:
        return BreakdownFilter(
            breakdown=f"events.properties.{self.breakdown_key}",
            breakdown_type="data_warehouse",
        )

    def _get_metric_type(self) -> ExperimentMetricType:
        # Currently, we rely on the math type to determine the metric type
        match self.query.count_query.series[0].math:
            case PropertyMathType.SUM | "hogql":
                return ExperimentMetricType.CONTINUOUS
            case _:
                return ExperimentMetricType.COUNT

    def _prepare_count_query(self) -> TrendsQuery:
        """
        This method takes the raw trend query and adapts it
        for the needs of experiment analysis:

        1. Set the trend display type based on whether math aggregation is used
        2. Set the date range to match the experiment's duration, using the project's timezone.
        3. Configure the breakdown to use the feature flag key, which allows us
           to separate results for different experiment variants.
        """
        prepared_count_query = TrendsQuery(**self.query.count_query.model_dump())

        prepared_count_query.trendsFilter = TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)
        prepared_count_query.dateRange = self._get_date_range()
        if self._is_data_warehouse_query(prepared_count_query):
            prepared_count_query.breakdownFilter = self._get_data_warehouse_breakdown_filter()
            prepared_count_query.properties = [
                DataWarehousePropertyFilter(
                    key="events.event",
                    value="$feature_flag_called",
                    operator=PropertyOperator.EXACT,
                    type="data_warehouse",
                ),
                DataWarehousePropertyFilter(
                    key=f"events.properties.{self.breakdown_key}",
                    value=self.variants,
                    operator=PropertyOperator.EXACT,
                    type="data_warehouse",
                ),
            ]
        else:
            prepared_count_query.breakdownFilter = self._get_event_breakdown_filter()
            prepared_count_query.properties = [
                EventPropertyFilter(
                    key=self.breakdown_key,
                    value=self.variants,
                    operator=PropertyOperator.EXACT,
                    type="event",
                )
            ]

        return prepared_count_query

    def _prepare_exposure_query(self) -> TrendsQuery:
        """
        Exposure is the count of users who have seen the experiment. This is necessary to calculate the statistical
        significance of the experiment.

        There are 2 possible cases for the exposure query:
        1. Otherwise, if an exposure query is provided, we use it as is, adapting it to the experiment's duration and breakdown
        2. Otherwise, we construct a default exposure query (the count of $feature_flag_called events)
        """

        prepared_count_query = TrendsQuery(**self.query.count_query.model_dump())

        # 1. If an exposure query is provided, we use it as is, adapting it to the experiment's duration and breakdown
        if self.query.exposure_query and not self._is_data_warehouse_query(prepared_count_query):
            prepared_exposure_query = TrendsQuery(**self.query.exposure_query.model_dump())
            prepared_exposure_query.dateRange = self._get_date_range()
            prepared_exposure_query.trendsFilter = TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)
            prepared_exposure_query.breakdownFilter = self._get_event_breakdown_filter()
            prepared_exposure_query.properties = [
                EventPropertyFilter(
                    key=self.breakdown_key,
                    value=self.variants,
                    operator=PropertyOperator.EXACT,
                    type="event",
                )
            ]
        # 2. Otherwise, we construct a default exposure query: unique users for the $feature_flag_called event
        else:
            prepared_exposure_query = TrendsQuery(
                dateRange=self._get_date_range(),
                trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE),
                breakdownFilter=BreakdownFilter(
                    breakdown="$feature_flag_response",
                    breakdown_type="event",
                ),
                series=[
                    EventsNode(
                        event="$feature_flag_called",
                        math=BaseMathType.DAU,  # TODO sync with frontend!!!
                    )
                ],
                properties=[
                    EventPropertyFilter(
                        key="$feature_flag_response",
                        value=self.variants,
                        operator=PropertyOperator.EXACT,
                        type="event",
                    ),
                    EventPropertyFilter(
                        key="$feature_flag",
                        value=[self.feature_flag.key],
                        operator=PropertyOperator.EXACT,
                        type="event",
                    ),
                ],
                filterTestAccounts=self.query.count_query.filterTestAccounts,
            )

        return prepared_exposure_query

    def calculate(self) -> ExperimentTrendsQueryResponse:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            query_type="ExperimentTrendsQuery",
            experiment_id=str(self.experiment.id),
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
        )

        shared_results: dict[str, Optional[Any]] = {"count_result": None, "exposure_result": None}
        errors = []

        def run(query_runner: TrendsQueryRunner, result_key: str, is_parallel: bool):
            try:
                result = query_runner.calculate()
                shared_results[result_key] = result
            except Exception as e:
                errors.append(e)
            finally:
                if is_parallel:
                    from django.db import connection

                    # This will only close the DB connection for the newly spawned thread and not the whole app
                    connection.close()

        # This exists so that we're not spawning threads during unit tests
        if settings.IN_UNIT_TESTING:
            run(self.count_query_runner, "count_result", False)
            run(self.exposure_query_runner, "exposure_result", False)
        else:
            jobs = [
                threading.Thread(target=run, args=(self.count_query_runner, "count_result", True)),
                threading.Thread(target=run, args=(self.exposure_query_runner, "exposure_result", True)),
            ]
            [j.start() for j in jobs]  # type: ignore
            [j.join() for j in jobs]  # type: ignore

        # Raise any errors raised in a separate thread
        if errors:
            raise errors[0]

        count_result = shared_results["count_result"]
        exposure_result = shared_results["exposure_result"]
        if count_result is None or exposure_result is None:
            raise ValueError("One or both query runners failed to produce a response")

        self._validate_event_variants(count_result, exposure_result)

        # Statistical analysis
        control_variant, test_variants = self._get_variants_with_base_stats(count_result, exposure_result)
        match self._get_metric_type():
            case ExperimentMetricType.CONTINUOUS:
                probabilities = calculate_probabilities_v2_continuous(control_variant, test_variants)
                significance_code, p_value = are_results_significant_v2_continuous(
                    control_variant, test_variants, probabilities
                )
                credible_intervals = calculate_credible_intervals_v2_continuous([control_variant, *test_variants])
            case ExperimentMetricType.COUNT:
                probabilities = calculate_probabilities_v2_count(control_variant, test_variants)
                significance_code, p_value = are_results_significant_v2_count(
                    control_variant, test_variants, probabilities
                )
                credible_intervals = calculate_credible_intervals_v2_count([control_variant, *test_variants])
            case _:
                raise ValueError(f"Unsupported metric type: {self._get_metric_type()}")

        return ExperimentTrendsQueryResponse(
            kind="ExperimentTrendsQuery",
            insight=count_result.results,
            count_query=self.prepared_count_query,
            exposure_query=self.prepared_exposure_query,
            variants=[variant.model_dump() for variant in [control_variant, *test_variants]],
            probability={
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            },
            significant=significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            significance_code=significance_code,
            stats_version=2,
            p_value=p_value,
            credible_intervals=credible_intervals,
        )

    def _get_variants_with_base_stats(
        self, count_results: TrendsQueryResponse, exposure_results: TrendsQueryResponse
    ) -> tuple[ExperimentVariantTrendsBaseStats, list[ExperimentVariantTrendsBaseStats]]:
        control_variant: Optional[ExperimentVariantTrendsBaseStats] = None
        test_variants = []
        exposure_counts = {}
        exposure_ratios = {}

        for result in exposure_results.results:
            count = result.get("count", 0)
            breakdown_value = result.get("breakdown_value")
            exposure_counts[breakdown_value] = count

        control_exposure = exposure_counts.get(CONTROL_VARIANT_KEY, 0)

        if control_exposure != 0:
            for key, count in exposure_counts.items():
                exposure_ratios[key] = count / control_exposure

        for result in count_results.results:
            count = result.get("count", 0)
            breakdown_value = result.get("breakdown_value")
            if breakdown_value == CONTROL_VARIANT_KEY:
                absolute_exposure = exposure_counts.get(breakdown_value, 0)
                control_variant = ExperimentVariantTrendsBaseStats(
                    key=breakdown_value,
                    count=count,
                    exposure=1,
                    absolute_exposure=absolute_exposure,
                )
            else:
                absolute_exposure = exposure_counts.get(breakdown_value, 0)
                test_variants.append(
                    ExperimentVariantTrendsBaseStats(
                        key=breakdown_value,
                        count=count,
                        exposure=exposure_ratios.get(breakdown_value, 0),
                        absolute_exposure=absolute_exposure,
                    )
                )

        if control_variant is None:
            raise ValueError("Control variant not found in count results")

        return control_variant, test_variants

    def _validate_event_variants(self, count_result: TrendsQueryResponse, exposure_result: TrendsQueryResponse):
        errors = {
            ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
            ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
            ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
        }

        # Don't throw right away because we want to validate metric events too
        # If metric events pass, the end of the function will still throw an error
        if exposure_result.results:
            errors[ExperimentNoResultsErrorKeys.NO_EXPOSURES] = False

        if not count_result.results or not count_result.results[0]:
            raise ValidationError(code="no-results", detail=json.dumps(errors))

        # Check if "control" is present
        for event in count_result.results:
            event_variant = event.get("breakdown_value")
            if event_variant == "control":
                errors[ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT] = False
                break
        # Check if at least one of the test variants is present
        test_variants = [variant for variant in self.variants if variant != "control"]

        for event in count_result.results:
            event_variant = event.get("breakdown_value")
            if event_variant in test_variants:
                errors[ExperimentNoResultsErrorKeys.NO_TEST_VARIANT] = False
                break

        has_errors = any(errors.values())
        if has_errors:
            raise ValidationError(detail=json.dumps(errors))

    def _is_data_warehouse_query(self, query: TrendsQuery) -> bool:
        return isinstance(query.series[0], DataWarehouseNode)

    def to_query(self) -> ast.SelectQuery:
        raise ValueError(f"Cannot convert source query of type {self.query.count_query.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
