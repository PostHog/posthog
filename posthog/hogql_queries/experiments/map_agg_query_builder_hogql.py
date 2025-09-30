"""
Map Aggregation Query Builder for Experiments (Plain HogQL Version)

This module implements the same single-scan query approach as map_agg_query_builder.py,
but uses plain HogQL strings instead of Python AST construction. This is more concise
and easier to read/maintain.

Performance: Expected 2-10x speedup compared to self-join approach.
"""

from posthog.schema import (
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_exposure_event_and_property,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.models.team.team import Team


class MapAggregationQueryBuilderHogQL:
    """
    Builds a single-scan experiment query using map aggregations.
    Uses plain HogQL string syntax for readability.
    """

    def __init__(
        self,
        experiment: Experiment,
        team: Team,
        metric: ExperimentMeanMetric,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        multiple_variant_handling: MultipleVariantHandling,
    ):
        self.experiment = experiment
        self.team = team
        self.metric = metric
        self.variants = variants
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.multiple_variant_handling = multiple_variant_handling

        self.feature_flag = experiment.feature_flag
        self.exposure_criteria = experiment.exposure_criteria

        # Get exposure event details
        self.exposure_event, self.feature_flag_variant_property = get_exposure_event_and_property(
            feature_flag_key=self.feature_flag.key,
            exposure_criteria=self.exposure_criteria,
        )

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL string.
        """
        query_string = self._build_query_string()
        return parse_select(query_string)

    def _build_query_string(self) -> str:
        """
        Builds the complete query as a HogQL string.
        """
        # Get parameters
        timezone = self.team.timezone or "UTC"
        team_id = self.team.pk
        date_from = self.date_range_query.date_from()
        date_to = self.date_range_query.date_to()

        # Build variant list for IN clause
        variants_list = ", ".join(f"'{v}'" for v in self.variants)

        # Get metric source details
        math_type = getattr(self.metric.source, "math", ExperimentMetricMathType.TOTAL)
        event_name = self.metric.source.event if hasattr(self.metric.source, "event") else None
        math_property = getattr(self.metric.source, "math_property", None)

        # Build value expression for metric events
        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            value_expr = "`$session_id`"
        elif math_type == ExperimentMetricMathType.DAU:
            value_expr = "person_id"
        elif math_property:
            value_expr = f"properties.{math_property}"
        else:
            value_expr = "1"  # For counting events

        # Build conversion window constraint
        conversion_window_constraint = ""
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )
            conversion_window_constraint = f"AND toTimeZone(timestamp, '{timezone}') < toDateTime('{date_to}', '{timezone}') + INTERVAL {conversion_window_seconds} SECOND"
        else:
            conversion_window_constraint = (
                f"AND toTimeZone(timestamp, '{timezone}') < toDateTime('{date_to}', '{timezone}')"
            )

        # Build variant selection expression
        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant_expr = f"argMinIf(properties.{self.feature_flag_variant_property}, timestamp, exposure_predicate)"
        else:
            variant_expr = f"""if(
                uniqExactIf(properties.{self.feature_flag_variant_property}, exposure_predicate) > 1,
                '{MULTIPLE_VARIANT_KEY}',
                anyIf(properties.{self.feature_flag_variant_property}, exposure_predicate)
            )"""

        # Build value aggregation based on math type
        value_agg = self._get_value_aggregation_expr(math_type)

        # Build the query
        query = f"""
        SELECT
            metric_events.variant AS variant,
            count(metric_events.entity_id) AS num_users,
            sum(metric_events.value) AS total_sum,
            sum(power(metric_events.value, 2)) AS total_sum_of_squares
        FROM (
            SELECT
                events_enriched.entity_id AS entity_id,
                events_enriched.variant AS variant,
                events_enriched.exposure_event_uuid AS exposure_event_uuid,
                events_enriched.exposure_session_id AS exposure_session_id,
                arrayFilter(x -> x.1 >= events_enriched.first_exposure_time, events_enriched.metric_events_array) AS metric_after_exposure,
                {value_agg} AS value
            FROM (
                SELECT
                    {self.entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    minIf(toTimeZone(timestamp, '{timezone}'), exposure_predicate) AS first_exposure_time,
                    argMinIf(uuid, toTimeZone(timestamp, '{timezone}'), exposure_predicate) AS exposure_event_uuid,
                    argMinIf(`$session_id`, toTimeZone(timestamp, '{timezone}'), exposure_predicate) AS exposure_session_id,
                    groupArrayIf(
                        tuple(toTimeZone(timestamp, '{timezone}'), {value_expr}),
                        metric_predicate
                    ) AS metric_events_array
                FROM events
                WHERE (exposure_predicate OR metric_predicate)
                GROUP BY entity_id
            ) AS events_enriched
            WHERE events_enriched.first_exposure_time IS NOT NULL
        ) AS metric_events
        GROUP BY metric_events.variant
        """

        # Now replace the predicate placeholders with actual conditions
        exposure_predicate = self._build_exposure_predicate_string(timezone, date_from, date_to)
        metric_predicate = self._build_metric_predicate_string(
            timezone, date_from, date_to, event_name, conversion_window_constraint
        )

        # Replace placeholders
        query = query.replace("exposure_predicate", exposure_predicate)
        query = query.replace("metric_predicate", metric_predicate)

        return query

    def _build_exposure_predicate_string(self, timezone: str, date_from, date_to) -> str:
        """
        Builds the exposure predicate as a string.
        """
        variants_list = ", ".join(f"'{v}'" for v in self.variants)

        predicate = f"""(
            toTimeZone(timestamp, '{timezone}') >= toDateTime('{date_from}', '{timezone}')
            AND toTimeZone(timestamp, '{timezone}') <= toDateTime('{date_to}', '{timezone}')
            AND event = '{self.exposure_event}'
            AND properties.{self.feature_flag_variant_property} IN [{variants_list}]
        """

        if self.exposure_event == "$feature_flag_called":
            predicate += f" AND properties.`$feature_flag` = '{self.feature_flag.key}'"

        predicate += ")"

        return predicate

    def _build_metric_predicate_string(
        self, timezone: str, date_from, date_to, event_name: str, conversion_window_constraint: str
    ) -> str:
        """
        Builds the metric predicate as a string.
        """
        predicate = f"""(
            toTimeZone(timestamp, '{timezone}') >= toDateTime('{date_from}', '{timezone}')
            {conversion_window_constraint}
            AND event = '{event_name}'
        )"""

        return predicate

    def _get_value_aggregation_expr(self, math_type: ExperimentMetricMathType) -> str:
        """
        Returns the value aggregation expression based on math type.
        """
        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            return "toFloat(length(arrayDistinct(arrayMap(x -> x.2, metric_after_exposure))))"
        elif math_type in [ExperimentMetricMathType.DAU, ExperimentMetricMathType.UNIQUE_GROUP]:
            return "toFloat(length(arrayDistinct(arrayMap(x -> x.2, metric_after_exposure))))"
        elif math_type == ExperimentMetricMathType.MIN:
            return "arrayMin(arrayMap(x -> coalesce(toFloat(x.2), 0), metric_after_exposure))"
        elif math_type == ExperimentMetricMathType.MAX:
            return "arrayMax(arrayMap(x -> coalesce(toFloat(x.2), 0), metric_after_exposure))"
        elif math_type == ExperimentMetricMathType.AVG:
            return "arrayAvg(arrayMap(x -> coalesce(toFloat(x.2), 0), metric_after_exposure))"
        else:
            # Default: SUM or TOTAL
            return "arraySum(arrayMap(x -> coalesce(toFloat(x.2), 0), metric_after_exposure))"
