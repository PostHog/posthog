from typing import cast

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, ExperimentFunnelMetric, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.experiments.base_query_utils import funnel_steps_to_filter
from posthog.hogql_queries.experiments.experiment_query_builder import ExperimentQueryBuilder
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team


class ExperimentFunnelActorsQueryBuilder(ExperimentQueryBuilder):
    """
    Builds actors query for experiment funnels with exposure filtering.

    Extends ExperimentQueryBuilder to reuse exposure filtering logic while
    adding actor-specific selection and filtering.

    Query structure:
    1. exposures CTE: First exposure per entity (same as main query)
    2. metric_events CTE: All metric events (funnel steps 1-N)
    3. entity_metrics CTE: Funnel evaluation with exposure as step 0
    4. actors query: Filter to specific step and variant, return person details
    """

    def __init__(
        self,
        team: Team,
        feature_flag_key: str,
        exposure_config: ExperimentEventExposureConfig | ActionsNode,
        filter_test_accounts: bool,
        multiple_variant_handling: MultipleVariantHandling,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        metric: ExperimentFunnelMetric,
        funnel_step: int,
        funnel_step_breakdown: str | int | float,
        include_recordings: bool,
    ):
        super().__init__(
            team=team,
            feature_flag_key=feature_flag_key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=variants,
            date_range_query=date_range_query,
            entity_key=entity_key,
            metric=metric,
        )
        self.funnel_step = funnel_step
        self.funnel_step_breakdown = funnel_step_breakdown
        self.include_recordings = include_recordings

    def build_actors_query(self) -> ast.SelectQuery:
        """
        Build the complete actors query with exposure filtering.

        Returns persons who:
        - Were exposed to the specified variant
        - Completed the specified funnel step (or dropped off at that step)
        - Only considers events that occurred AFTER their first exposure
        """
        # Build the base query structure with CTEs
        query = self._build_base_query_with_ctes()

        # Add actors-specific SELECT and WHERE
        query = self._add_actors_selection(query)
        query = self._add_actors_where_clause(query)

        # Add ORDER BY for consistent results
        query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["entity_id"]))]

        return query

    def _build_base_query_with_ctes(self) -> ast.SelectQuery:
        """
        Build query with exposures, metric_events, and entity_metrics CTEs.

        This mirrors the main experiment query structure but focuses on
        individual users rather than aggregate statistics.
        """
        # Use parent class methods to build exposure and metric CTEs
        exposure_select_query = self._get_exposure_query()

        # Build metric events CTE
        metric_events_cte = self._build_metric_events_cte()

        # Build entity metrics CTE with funnel evaluation
        entity_metrics_cte = self._build_entity_metrics_cte()

        # Construct the query with CTEs
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            WITH
                exposures AS ({exposure_query}),
                metric_events AS ({metric_events_query}),
                entity_metrics AS ({entity_metrics_query})

            SELECT * FROM entity_metrics
            """,
                placeholders={
                    "exposure_query": exposure_select_query,
                    "metric_events_query": metric_events_cte,
                    "entity_metrics_query": entity_metrics_cte,
                },
            ),
        )

        return query

    def _build_metric_events_cte(self) -> ast.SelectQuery:
        """
        Build the metric_events CTE with all funnel step events.

        Includes step_0 (exposure), step_1, step_2, ... (metric events)
        """
        # Ensure metric is ExperimentFunnelMetric (validated in parent constructor)
        assert isinstance(self.metric, ExperimentFunnelMetric), "metric must be ExperimentFunnelMetric"

        # Get date range predicates
        date_from = self.date_range_query.date_from_as_hogql()
        date_to = self.date_range_query.date_to_as_hogql()

        # Build funnel steps filter
        funnel_steps_filter = funnel_steps_to_filter(self.team, self.metric.series)

        # Build exposure predicate
        exposure_predicate = self._build_exposure_event_predicate()

        # Parse base query without step columns
        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {entity_key} AS entity_id,
                timestamp,
                uuid,
                properties.$session_id AS session_id,
                1 * ({exposure_predicate}) AS step_0
            FROM events
            WHERE timestamp >= {date_from}
                AND timestamp <= {date_to}
                AND ({exposure_predicate} OR {funnel_steps_filter})
            """,
                placeholders={
                    "entity_key": parse_expr(self.entity_key),
                    "exposure_predicate": exposure_predicate,
                    "funnel_steps_filter": funnel_steps_filter,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            ),
        )

        # Add step columns dynamically using parent class method
        # Parent's _build_funnel_step_columns() returns [step_0, step_1, step_2, ...]
        # We skip step_0 (exposure) since it's not needed in metric_events CTE
        all_step_columns = self._build_funnel_step_columns()
        step_columns = all_step_columns[1:]  # Skip step_0, keep step_1, step_2, ...
        query.select.extend(step_columns)

        return query

    def _build_entity_metrics_cte(self) -> ast.SelectQuery:
        """
        Build entity_metrics CTE with funnel evaluation.

        Uses aggregate_funnel_array UDF with exposure as step 0.
        Includes matched_events_array for recording support.
        """
        # Ensure metric is ExperimentFunnelMetric (validated in parent constructor)
        assert isinstance(self.metric, ExperimentFunnelMetric), "metric must be ExperimentFunnelMetric"

        # Determine if unordered funnel (needs temporal filter)
        is_unordered = self.metric.funnel_order_type == "unordered"
        temporal_filter = "AND metric_events.timestamp >= exposures.first_exposure_time" if is_unordered else ""

        # Build conversion window
        if self.metric.conversion_window is not None and self.metric.conversion_window_unit is not None:
            from posthog.hogql_queries.experiments.base_query_utils import conversion_window_to_seconds

            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window, self.metric.conversion_window_unit
            )
        else:
            # Default to 3 years
            conversion_window_seconds = 3 * 365 * 24 * 60 * 60

        num_steps = len(self.metric.series) + 1  # +1 for exposure
        funnel_order_type = self.metric.funnel_order_type or "ordered"

        # Build step conditions for aggregate_funnel_array
        step_conditions = [f"{i + 1} * metric_events.step_{i}" for i in range(num_steps)]
        step_conditions_str = ", ".join(step_conditions)

        # Build recordings support fields if requested
        if self.include_recordings:
            recordings_fields = """
                groupArray(tuple(metric_events.timestamp, metric_events.uuid, metric_events.session_id, '')) as user_events,
                mapFromArrays(arrayMap(x -> x.2, user_events), user_events) as user_events_map,
                arraySort(x -> -x.1,
                    aggregate_funnel_array(
                        {num_steps},
                        {conversion_window_seconds},
                        'first_touch',
                        '{funnel_order_type}',
                        array(array('')),
                        [],
                        arraySort(t -> t.1, groupArray(tuple(
                            toFloat(metric_events.timestamp),
                            metric_events.uuid,
                            array(''),
                            arrayFilter(x -> x > 0, [{step_conditions_str}])
                        )))
                    )
                )[1] as af_tuple,
                af_tuple.1 as step_reached,
                af_tuple.4 as matched_event_uuids_array_array,
                arrayMap(matched_event_uuids_array -> arrayMap(event_uuid -> user_events_map[event_uuid], arrayDistinct(matched_event_uuids_array)), matched_event_uuids_array_array) as matched_events_array
            """.format(
                num_steps=num_steps,
                conversion_window_seconds=conversion_window_seconds,
                funnel_order_type=funnel_order_type,
                step_conditions_str=step_conditions_str,
            )
        else:
            # Without recordings, just compute step_reached using funnel_evaluation_expr
            from posthog.hogql_queries.experiments.base_query_utils import funnel_evaluation_expr

            funnel_agg_expr = funnel_evaluation_expr(
                self.team,
                self.metric,
                events_alias="metric_events",
                include_exposure=True,
            )
            # Extract step_reached from the funnel evaluation result
            # The result is arraySort with tuple(step_reached, uuid_string)
            # We want the .1 element which is step_reached
            recordings_fields = ""

        # Build the complete SELECT query
        # Note: recordings_fields and temporal_filter are internally computed safe strings
        # covered by semgrep exception (see .semgrep/rules/hogql-no-fstring.yaml line 114)
        query = cast(
            ast.SelectQuery,
            parse_select(
                f"""
            SELECT
                exposures.entity_id AS entity_id,
                exposures.variant AS variant,
                exposures.exposure_event_uuid AS exposure_event_uuid
                {("," + recordings_fields) if recordings_fields else ""}
            FROM exposures
            LEFT JOIN metric_events
                ON exposures.entity_id = metric_events.entity_id
                {temporal_filter}
            GROUP BY
                exposures.entity_id,
                exposures.variant,
                exposures.exposure_event_uuid
            """
            ),
        )

        # If not including recordings, add step_reached using funnel_evaluation_expr
        if not self.include_recordings:
            query.select.append(
                ast.Alias(
                    alias="step_reached",
                    expr=ast.TupleAccess(tuple=funnel_agg_expr, index=1, nullish=False),
                )
            )

        return query

    def _add_actors_selection(self, query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Add actor-specific SELECT columns.

        Returns entity_id, variant, and optionally matching_events for recordings support.
        """
        select_exprs: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["entity_id"])),
            ast.Alias(alias="variant", expr=ast.Field(chain=["variant"])),
        ]

        # Add matching_events field only when recordings are requested
        if self.include_recordings:
            # For conversions and drop-offs, select events from the reached step
            # step_reached is 0-indexed, so we add 1 to get the array index
            select_exprs.append(
                ast.Alias(
                    alias="matching_events",
                    expr=parse_expr("matched_events_array[step_reached + 1]"),
                )
            )

        query.select = select_exprs
        return query

    def _add_actors_where_clause(self, query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Add WHERE clause to filter to specific step and variant.

        Mirrors the step filtering logic from FunnelBase._get_funnel_person_step_condition
        """
        conditions: list[ast.Expr] = []

        # Filter by step
        # NOTE: step_reached is 0-indexed and includes exposure as step 0
        # - step_reached = 0: completed exposure only
        # - step_reached = 1: completed exposure + first metric
        # - step_reached = 2: completed exposure + first + second metric
        # funnelStep is 1-indexed for metric steps (exposure is not counted):
        # - funnelStep = 1: first metric step
        # - funnelStep = 2: second metric step

        if self.funnel_step >= 0:
            # Conversion: user reached this step
            # funnelStep=1 (first metric) requires step_reached >= 1 (exposure + first metric)
            # funnelStep=2 (second metric) requires step_reached >= 2 (exposure + first + second metric)
            # Formula: step_reached >= funnel_step
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=self.funnel_step),
                )
            )
        else:
            # Drop-off: user reached prior step but NOT this step
            # funnelStep=-2 means dropped at step 2: completed step 1 (first metric) but NOT step 2 (second metric)
            # In step_reached terms: step_reached >= 1 AND step_reached < 2
            # Formula for funnelStep=-N: step_reached >= (N-1) AND step_reached < N
            target_step = abs(self.funnel_step)

            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=target_step - 1),
                )
            )
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=target_step),
                )
            )

        # Filter by variant (skip if empty string or None)
        if self.funnel_step_breakdown:
            if isinstance(self.funnel_step_breakdown, int | float):
                variant_value = str(int(self.funnel_step_breakdown))
            else:
                variant_value = self.funnel_step_breakdown

            conditions.append(
                parse_expr(
                    "variant = {variant}",
                    {"variant": ast.Constant(value=variant_value)},
                )
            )

        query.where = ast.And(exprs=conditions) if conditions else None
        return query
