from datetime import datetime, timedelta
from math import ceil
from typing import Any, Optional, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AggregationType,
    Breakdown,
    BreakdownType,
    CachedRetentionQueryResponse,
    EntityType,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    InCohortVia,
    IntervalType,
    RetentionEntity,
    RetentionQuery,
    RetentionQueryResponse,
    RetentionType,
)

from posthog.hogql import ast
from posthog.hogql.constants import (
    MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
    HogQLGlobalSettings,
    LimitContext,
    get_breakdown_limit_for_context,
)
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import entity_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.hogql_queries.insights.retention.retention_base_query_fixed import RetentionFixedIntervalBaseQueryBuilder
from posthog.hogql_queries.insights.retention.retention_base_query_rolling import (
    RetentionRollingIntervalBaseQueryBuilder,
)
from posthog.hogql_queries.insights.retention.utils import has_cohort_property
from posthog.hogql_queries.insights.trends.breakdown import BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.insights.utils.breakdowns import has_breakdown_filter, has_single_breakdown
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID
from posthog.queries.util import correct_result_for_sampling

DEFAULT_INTERVAL = IntervalType("day")
DEFAULT_TOTAL_INTERVALS = 7

DEFAULT_ENTITY = RetentionEntity(
    **{
        "id": "$pageview",
        "type": TREND_FILTER_TYPE_EVENTS,
    }
)


class RetentionQueryRunner(AnalyticsQueryRunner[RetentionQueryResponse]):
    query: RetentionQuery
    cached_response: CachedRetentionQueryResponse
    start_event: RetentionEntity
    return_event: RetentionEntity

    def __init__(
        self,
        query: RetentionQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(
            query=query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            # retention queries require higher row limit as breakdowns + big date ranges can push past 50k rows
            limit_context=(
                LimitContext.RETENTION
                if not limit_context or limit_context in (LimitContext.QUERY_ASYNC, LimitContext.QUERY)
                else limit_context
            ),
        )

        self.start_event = self.query.retentionFilter.targetEntity or DEFAULT_ENTITY
        self.return_event = self.query.retentionFilter.returningEntity or DEFAULT_ENTITY

        # standardize breakdown schema
        if self.query.breakdownFilter:
            self.convert_single_breakdown_to_multiple_breakdowns()
            # Clean up old fields
            self.query.breakdownFilter.breakdown = None
            self.query.breakdownFilter.breakdown_type = None

        self.__post_init__()

    def __post_init__(self) -> None:
        self.validate()

        # Called after __init__ and after dashboard filters are applied. This ensures cohort optimizations work for both direct filters and dashboard-level filters.
        self.update_hogql_modifiers()

    def validate(self) -> None:
        if (
            self.query.retentionFilter
            and self.query.retentionFilter.timeWindowMode == "24_hour_windows"
            and self.query.retentionFilter.cumulative
        ):
            raise ValidationError("Cumulative retention is not supported for 24 hour windows.")

    def update_hogql_modifiers(self) -> None:
        """
        Update HogQL modifiers to optimize cohort filtering performance.
        Use LEFTJOIN mode instead of SUBQUERY for cohort filters to enable better query optimization.
        """
        if self.modifiers.inCohortVia == InCohortVia.AUTO:
            # Check if we have cohort filters in properties
            has_cohort_filter = False

            if self.query.properties:
                has_cohort_filter = has_cohort_property(self.query.properties)

            # Check if we have cohort breakdown
            if not has_cohort_filter and self.query.breakdownFilter:
                if self.query.breakdownFilter.breakdown_type == "cohort" or (
                    self.query.breakdownFilter.breakdowns
                    and any(b.type == "cohort" for b in self.query.breakdownFilter.breakdowns)
                ):
                    has_cohort_filter = True

            # Use LEFTJOIN for cohort filters to avoid slow subquery evaluation
            if has_cohort_filter:
                self.modifiers.inCohortVia = InCohortVia.LEFTJOIN

    @cached_property
    def property_aggregation_expr(self) -> ast.Expr | None:
        if (
            self.query.retentionFilter.aggregationType in [AggregationType.SUM, AggregationType.AVG]
            and self.query.retentionFilter.aggregationProperty
        ):
            prop_name = self.query.retentionFilter.aggregationProperty
            if self.query.retentionFilter.aggregationPropertyType == "person":
                # person.properties resolves via the HogQL person join on the events table
                chain = cast(list[str | int], ["person", "properties", prop_name])
            else:
                chain = cast(list[str | int], ["events", "properties", prop_name])
            property_field = ast.Field(chain=chain)
            return ast.Call(
                name="ifNull",
                args=[
                    ast.Call(name="toFloat", args=[property_field]),
                    ast.Constant(value=0.0),
                ],
            )
        return None

    @cached_property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    @cached_property
    def is_custom_bracket_retention(self) -> bool:
        return (
            self.query.retentionFilter.retentionCustomBrackets is not None
            and len(self.query.retentionFilter.retentionCustomBrackets) > 0
        )

    @cached_property
    def lookahead_period_count(self) -> int:
        if self.is_custom_bracket_retention:
            assert self.query.retentionFilter.retentionCustomBrackets is not None
            # We add one, because the first period is the cohorting period
            return len(self.query.retentionFilter.retentionCustomBrackets) + 1
        return self.query_date_range.lookahead

    @cached_property
    def is_24h_window_calculation(self) -> bool:
        return self.query.retentionFilter.timeWindowMode == "24_hour_windows"

    @cached_property
    def is_first_occurrence_matching_filters(self) -> bool:
        return self.query.retentionFilter.retentionType == RetentionType.RETENTION_FIRST_TIME

    @cached_property
    def is_first_ever_occurrence(self) -> bool:
        return self.query.retentionFilter.retentionType == RetentionType.RETENTION_FIRST_EVER_OCCURRENCE

    @cached_property
    def start_entity_expr(self) -> ast.Expr:
        return entity_to_expr(self.start_event, self.team)

    @cached_property
    def return_entity_expr(self) -> ast.Expr:
        return entity_to_expr(self.return_event, self.team)

    @cached_property
    def aggregation_target_events_column(self) -> str:
        if self.group_type_index is not None:
            group_index = int(self.group_type_index)
            if 0 <= group_index <= 4:
                return f"$group_{group_index}"
        return "person_id"

    @cached_property
    def global_event_filters(self) -> list[ast.Expr]:
        global_event_filters = self.events_where_clause(
            self.is_first_occurrence_matching_filters, self.is_first_ever_occurrence
        )
        # Pre-filter events to only those we care about
        is_relevant_event = ast.Or(exprs=[self.start_entity_expr, self.return_entity_expr])
        if not self.is_first_ever_occurrence:
            global_event_filters.append(is_relevant_event)

        if self.group_type_index is not None:
            global_event_filters.append(
                ast.Not(
                    expr=ast.Call(
                        name="has",
                        args=[
                            ast.Array(exprs=[ast.Constant(value="")]),
                            ast.Field(chain=["events", f"$group_{self.group_type_index}"]),
                        ],
                    ),
                ),
            )
        return global_event_filters

    def convert_single_breakdown_to_multiple_breakdowns(self):
        if has_single_breakdown(self.query.breakdownFilter):
            assert self.query.breakdownFilter is not None  # type checking
            if self.query.breakdownFilter.breakdown_type == "cohort":
                # Ensure breakdown is always a list for cohorts
                breakdown_values = self.query.breakdownFilter.breakdown
                assert breakdown_values is not None  # type checking
                if not isinstance(breakdown_values, list):
                    breakdown_values = [breakdown_values]

                # Convert "all" to ALL_USERS_COHORT_ID (0) for frontend compatibility
                normalized_breakdown_values = []
                for cohort_id in breakdown_values:
                    if cohort_id == "all":
                        normalized_breakdown_values.append(ALL_USERS_COHORT_ID)
                    else:
                        normalized_breakdown_values.append(int(cohort_id))

                self.query.breakdownFilter.breakdowns = [
                    Breakdown(
                        type="cohort",
                        property=cohort_id,
                    )
                    for cohort_id in normalized_breakdown_values
                ]
            else:
                self.query.breakdownFilter.breakdowns = [
                    Breakdown(
                        type=self.query.breakdownFilter.breakdown_type,
                        property=self.query.breakdownFilter.breakdown,
                        group_type_index=self.query.breakdownFilter.breakdown_group_type_index,
                        histogram_bin_count=self.query.breakdownFilter.breakdown_histogram_bin_count,
                        normalize_url=self.query.breakdownFilter.breakdown_normalize_url,
                    )
                ]

    @cached_property
    def breakdowns_in_query(self) -> bool:
        return has_breakdown_filter(self.query.breakdownFilter)

    def events_timestamp_filter(self, field: ast.Expr | None = None) -> ast.Expr:
        """
        Timestamp filter between date_from and date_to
        """
        field_to_compare = field or ast.Field(chain=["events", "timestamp"])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=field_to_compare,
                    right=self.query_date_range.date_from_to_start_of_interval_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=field_to_compare,
                    right=ast.Constant(value=self.query_date_range.date_to()),
                ),
            ]
        )

    @cached_property
    def query_date_range(self) -> QueryDateRangeWithIntervals:
        if self.is_custom_bracket_retention:
            assert self.query.retentionFilter.retentionCustomBrackets is not None
            # For custom brackets, lookahead is sum of brackets, but total intervals for date range is from query
            intervals_to_look_ahead = sum(self.query.retentionFilter.retentionCustomBrackets)
            total_intervals = self.query.retentionFilter.totalIntervals or DEFAULT_TOTAL_INTERVALS
        else:
            intervals_to_look_ahead = self.query.retentionFilter.totalIntervals or DEFAULT_TOTAL_INTERVALS
            total_intervals = intervals_to_look_ahead

        interval = (
            IntervalType(self.query.retentionFilter.period.lower())
            if self.query.retentionFilter.period
            else DEFAULT_INTERVAL
        )

        return QueryDateRangeWithIntervals(
            date_range=self.query.dateRange,
            total_intervals=total_intervals,
            team=self.team,
            interval=interval,
            now=datetime.now(),
            lookahead_days=int(intervals_to_look_ahead) if self.is_custom_bracket_retention else None,
        )

    def get_events_for_entity(self, entity: RetentionEntity) -> list[str | None]:
        if entity.type == EntityType.ACTIONS and entity.id:
            action = Action.objects.get(pk=int(entity.id), team__project_id=self.team.project_id)
            return action.get_step_events()
        return [entity.id] if isinstance(entity.id, str) else [None]

    def events_where_clause(self, is_first_occurrence_matching_filters: bool, is_first_ever_occurrence: bool = False):
        """
        Event filters to apply to both start and return events
        """
        events_where = []

        if self.query.properties is not None and self.query.properties != []:
            events_where.append(property_to_expr(self.query.properties, self.team))

        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for prop in self.team.test_account_filters:
                events_where.append(property_to_expr(prop, self.team))

        if not is_first_occurrence_matching_filters and not is_first_ever_occurrence:
            # when it's recurring, we only have to grab events for the period, rather than events for all time
            events_where.append(self.events_timestamp_filter())

        # Pre-filter by event name
        events = self.get_events_for_entity(self.start_event) + self.get_events_for_entity(self.return_event)
        unique_events = set(events)
        # Don't pre-filter if any of them is "All events"
        if None not in unique_events:
            events_where.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    # Sorting for consistent snapshots in tests
                    right=ast.Tuple(exprs=[ast.Constant(value=event) for event in sorted(unique_events)]),  # type: ignore
                    op=ast.CompareOperationOp.In,
                )
            )

        return events_where

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def base_query(
        self,
        start_interval_index_filter: Optional[int] = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        builder_class = (
            RetentionRollingIntervalBaseQueryBuilder
            if self.is_24h_window_calculation
            else RetentionFixedIntervalBaseQueryBuilder
        )
        return builder_class(self).build(
            start_interval_index_filter=start_interval_index_filter,
            selected_breakdown_value=selected_breakdown_value,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        with self.timings.measure("retention_query"):
            base_query: ast.SelectQuery | ast.SelectSetQuery

            # is cohort breakdown
            if (
                self.query.breakdownFilter is not None
                and self.query.breakdownFilter.breakdowns is not None
                and any(b.type == "cohort" for b in self.query.breakdownFilter.breakdowns)
            ):
                base_queries = []
                cohort_breakdowns = [b for b in self.query.breakdownFilter.breakdowns if b.type == "cohort"]

                for breakdown in cohort_breakdowns:
                    temp_query = self.query.model_copy(deep=True)
                    if temp_query.breakdownFilter:
                        temp_query.breakdownFilter.breakdowns = [breakdown]
                        temp_query.breakdownFilter.breakdown = str(breakdown.property)
                        temp_query.breakdownFilter.breakdown_type = breakdown.type  # type: ignore

                    temp_runner = RetentionQueryRunner(
                        query=temp_query, team=self.team, timings=self.timings, modifiers=self.modifiers
                    )
                    base_queries.append(temp_runner.base_query())

                if len(base_queries) == 1:
                    base_query = base_queries[0]
                else:
                    base_query = ast.SelectSetQuery.create_from_queries(base_queries, "UNION ALL")
            else:
                base_query = self.base_query()

            if self.query.retentionFilter.cumulative:
                # For cumulative, we need to calculate the max interval and then explode it
                cumulative_actors_query = self._build_cumulative_actors_query(base_query)
                base_query = self._explode_cumulative_actors(cumulative_actors_query)

            # count_expr always represents the number of distinct actors
            count_expr = parse_expr("COUNT(DISTINCT actor_activity.actor_id)")

            # aggregation_value_expr is only used when property_aggregation_expr is set
            aggregation_value_expr: ast.Expr | None = None
            if self.property_aggregation_expr:
                if self.query.retentionFilter.aggregationType == AggregationType.AVG:
                    aggregation_value_expr = parse_expr(
                        "sum(actor_activity.retention_value) / COUNT(DISTINCT actor_activity.actor_id)"
                    )
                else:
                    aggregation_value_expr = parse_expr("sum(actor_activity.retention_value)")
                assert aggregation_value_expr is not None

            # Add breakdown if needed
            if self.breakdowns_in_query:
                if self.property_aggregation_expr:
                    assert aggregation_value_expr is not None
                    retention_query = parse_select(
                        """
                        SELECT
                            actor_activity.start_interval_index AS start_event_matching_interval,
                            actor_activity.intervals_from_base AS intervals_from_base,
                            actor_activity.breakdown_value AS breakdown_value,
                            {count_expr} AS count,
                            {aggregation_value_expr} AS aggregation_value

                        FROM {base_query} AS actor_activity

                        GROUP BY
                            start_event_matching_interval,
                            intervals_from_base,
                            breakdown_value

                        ORDER BY
                            breakdown_value,
                            start_event_matching_interval,
                            intervals_from_base

                        LIMIT 100000
                        """,
                        {
                            "base_query": base_query,
                            "count_expr": count_expr,
                            "aggregation_value_expr": aggregation_value_expr,
                        },
                        timings=self.timings,
                    )
                else:
                    retention_query = parse_select(
                        """
                        SELECT
                            actor_activity.start_interval_index AS start_event_matching_interval,
                            actor_activity.intervals_from_base AS intervals_from_base,
                            actor_activity.breakdown_value AS breakdown_value,
                            {count_expr} AS count

                        FROM {base_query} AS actor_activity

                        GROUP BY
                            start_event_matching_interval,
                            intervals_from_base,
                            breakdown_value

                        ORDER BY
                            breakdown_value,
                            start_event_matching_interval,
                            intervals_from_base

                        LIMIT 100000
                        """,
                        {"base_query": base_query, "count_expr": count_expr},
                        timings=self.timings,
                    )
            else:
                if self.property_aggregation_expr:
                    assert aggregation_value_expr is not None
                    retention_query = parse_select(
                        """
                            SELECT actor_activity.start_interval_index     AS start_event_matching_interval,
                                   actor_activity.intervals_from_base      AS intervals_from_base,
                                   {count_expr} AS count,
                                   {aggregation_value_expr} AS aggregation_value

                            FROM {base_query} AS actor_activity

                            GROUP BY start_event_matching_interval,
                                     intervals_from_base

                            ORDER BY start_event_matching_interval,
                                     intervals_from_base

                            LIMIT 100000
                        """,
                        {
                            "base_query": base_query,
                            "count_expr": count_expr,
                            "aggregation_value_expr": aggregation_value_expr,
                        },
                        timings=self.timings,
                    )
                else:
                    retention_query = parse_select(
                        """
                            SELECT actor_activity.start_interval_index     AS start_event_matching_interval,
                                   actor_activity.intervals_from_base      AS intervals_from_base,
                                   {count_expr} AS count

                            FROM {base_query} AS actor_activity

                            GROUP BY start_event_matching_interval,
                                     intervals_from_base

                            ORDER BY start_event_matching_interval,
                                     intervals_from_base

                            LIMIT 100000
                        """,
                        {"base_query": base_query, "count_expr": count_expr},
                        timings=self.timings,
                    )
        return retention_query

    def _build_cumulative_actors_query(
        self, base_query: ast.SelectQuery | ast.SelectSetQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        # We need to calculate the max interval from the base query
        if self.breakdowns_in_query:
            return parse_select(
                """
                SELECT
                    actor_id,
                    max(intervals_from_base) as max_interval,
                    start_interval_index,
                    breakdown_value
                FROM {base_query}
                GROUP BY actor_id, start_interval_index, breakdown_value
                """,
                {"base_query": base_query},
            )
        else:
            return parse_select(
                """
                SELECT
                    actor_id,
                    max(intervals_from_base) as max_interval,
                    start_interval_index
                FROM {base_query}
                GROUP BY actor_id, start_interval_index
                """,
                {"base_query": base_query},
            )

    def _explode_cumulative_actors(
        self, cumulative_actors_query: ast.SelectQuery | ast.SelectSetQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.breakdowns_in_query:
            return parse_select(
                """
                SELECT
                    actor_id,
                    arrayJoin(range(0, max_interval + 1)) as intervals_from_base,
                    start_interval_index,
                    breakdown_value
                FROM {cumulative_actors_query}
                """,
                {"cumulative_actors_query": cumulative_actors_query},
            )
        else:
            return parse_select(
                """
                SELECT
                    actor_id,
                    arrayJoin(range(0, max_interval + 1)) as intervals_from_base,
                    start_interval_index
                FROM {cumulative_actors_query}
                """,
                {"cumulative_actors_query": cumulative_actors_query},
            )

    def get_date(self, interval: int):
        date = self.query_date_range.date_from() + self.query_date_range.determine_time_delta(
            interval, self.query_date_range.interval_name.title()
        )

        return date

    def get_bracket_labels(self) -> list[str]:
        labels: list[str] = [f"{self.query_date_range.interval_name.title()} 0"]
        if self.is_custom_bracket_retention and self.query.retentionFilter.retentionCustomBrackets:
            unit = self.query_date_range.interval_name.title()
            cumulative_total = 1  # Return periods start from day 1
            for bracket_size in self.query.retentionFilter.retentionCustomBrackets:
                bracket_size = int(bracket_size)
                start = cumulative_total
                end = cumulative_total + bracket_size - 1
                if start == end:
                    labels.append(f"{unit} {start}")
                else:
                    labels.append(f"{unit} {start}-{end}")
                cumulative_total += bracket_size
        else:
            for i in range(1, self.lookahead_period_count):
                labels.append(f"{self.query_date_range.interval_name.title()} {i}")

        return labels

    def _calculate(self) -> RetentionQueryResponse:
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            settings=HogQLGlobalSettings(max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY),
        )

        results = self.format_results(response)

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers)

    def format_results(self, response: HogQLQueryResponse) -> list[dict[str, Any]]:
        """Format raw retention HogQL response into nested interval structures.

        Columns are accessed by name to support arbitrary column ordering
        (materialized tables return columns alphabetically).
        Handles: breakdown ranking, 'Other' aggregation, sampling correction,
        bracket labels, date computation.
        """
        cols = {name: i for i, name in enumerate(response.columns or [])}
        has_aggregation_value = "aggregation_value" in cols

        if self.breakdowns_in_query:
            # Step 1: Calculate total cohort size for each breakdown value (size at intervals_from_base = 0)
            breakdown_totals: dict[str, int] = {}
            original_results = response.results or []
            for row in original_results:
                start_interval = row[cols["start_event_matching_interval"]]
                intervals_from_base = row[cols["intervals_from_base"]]
                breakdown_value = row[cols["breakdown_value"]]
                count = row[cols["count"]]
                if intervals_from_base == 0:
                    breakdown_totals[breakdown_value] = breakdown_totals.get(breakdown_value, 0) + count

            # Step 2: Rank breakdowns and determine top N and 'Other'
            breakdown_limit = (
                self.query.breakdownFilter.breakdown_limit
                if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_limit is not None
                else get_breakdown_limit_for_context(self.limit_context)
            )
            sorted_breakdowns = sorted(breakdown_totals.items(), key=lambda item: (-item[1], item[0]))
            other_values = {item[0] for item in sorted_breakdowns[breakdown_limit:]}

            # Step 3: Aggregate results, grouping less frequent breakdowns into 'Other'
            aggregated_count_data: dict[str, dict[int, dict[int, float]]] = {}
            aggregated_value_data: dict[str, dict[int, dict[int, float]]] = {}
            for row in original_results:
                start_interval = row[cols["start_event_matching_interval"]]
                intervals_from_base = row[cols["intervals_from_base"]]
                breakdown_value = row[cols["breakdown_value"]]
                count = row[cols["count"]]
                aggregation_value = row[cols["aggregation_value"]] if has_aggregation_value else None

                target_breakdown = breakdown_value
                if breakdown_value in other_values:
                    target_breakdown = BREAKDOWN_OTHER_STRING_LABEL

                corrected_count = correct_result_for_sampling(count, self.query.samplingFactor)

                aggregated_count_data[target_breakdown] = aggregated_count_data.get(target_breakdown, {})
                breakdown_data = aggregated_count_data[target_breakdown]
                breakdown_data[start_interval] = breakdown_data.get(start_interval, {})
                interval_data = breakdown_data[start_interval]
                interval_data[intervals_from_base] = interval_data.get(intervals_from_base, 0) + corrected_count

                if self.property_aggregation_expr and aggregation_value is not None:
                    corrected_aggregation_value = correct_result_for_sampling(
                        aggregation_value, self.query.samplingFactor
                    )
                    aggregated_value_data[target_breakdown] = aggregated_value_data.get(target_breakdown, {})
                    value_breakdown_data = aggregated_value_data[target_breakdown]
                    value_breakdown_data[start_interval] = value_breakdown_data.get(start_interval, {})
                    value_interval_data = value_breakdown_data[start_interval]
                    value_interval_data[intervals_from_base] = (
                        value_interval_data.get(intervals_from_base, 0.0) + corrected_aggregation_value
                    )

            # Step 4: Format final output
            final_results: list[dict[str, Any]] = []
            ordered_breakdown_keys = [item[0] for item in sorted_breakdowns[:breakdown_limit]]
            if other_values:
                ordered_breakdown_keys.append(BREAKDOWN_OTHER_STRING_LABEL)

            for breakdown_value in ordered_breakdown_keys:
                count_intervals_data: dict[int, dict[int, float]] = aggregated_count_data.get(breakdown_value, {})
                value_intervals_data: dict[int, dict[int, float]] = aggregated_value_data.get(breakdown_value, {})
                labels = self.get_bracket_labels()

                breakdown_results = []
                for start_interval in range(self.query_date_range.intervals_between):
                    count_result_dict: dict[int, float] = count_intervals_data.get(start_interval, {})
                    value_result_dict: dict[int, float] = value_intervals_data.get(start_interval, {})
                    values = [
                        {
                            "count": count_result_dict.get(return_interval, 0),
                            **(
                                {"aggregation_value": value_result_dict.get(return_interval, 0.0)}
                                if self.property_aggregation_expr
                                else {}
                            ),
                            "label": labels[return_interval],
                        }
                        for return_interval in range(self.lookahead_period_count)
                    ]

                    breakdown_results.append(
                        {
                            "values": values,
                            "label": f"{self.query_date_range.interval_name.title()} {start_interval}",
                            "date": self.get_date(start_interval),
                            "breakdown_value": breakdown_value,
                        }
                    )

                final_results.extend(breakdown_results)

            results = final_results
        else:
            results_by_interval_pair: dict[tuple[int, int], dict[str, float]] = {}
            for row in response.results or []:
                key = (row[cols["start_event_matching_interval"]], row[cols["intervals_from_base"]])
                count = correct_result_for_sampling(row[cols["count"]], self.query.samplingFactor)
                entry: dict[str, float] = {"count": count}
                if self.property_aggregation_expr and has_aggregation_value:
                    entry["aggregation_value"] = (
                        correct_result_for_sampling(row[cols["aggregation_value"]], self.query.samplingFactor) or 0.0
                    )
                results_by_interval_pair[key] = entry

            labels = self.get_bracket_labels()
            default_values: dict[str, float] = {"count": 0.0}
            if self.property_aggregation_expr and has_aggregation_value:
                default_values["aggregation_value"] = 0.0
            results = [
                {
                    "values": [
                        {
                            **results_by_interval_pair.get((start_interval, return_interval), default_values),
                            "label": labels[return_interval],
                        }
                        for return_interval in range(self.lookahead_period_count)
                    ],
                    "label": f"{self.query_date_range.interval_name.title()} {start_interval}",
                    "date": self.get_date(start_interval),
                    "breakdown_value": None,  # intentional to keep shape consistent
                }
                for start_interval in range(self.query_date_range.intervals_between)
            ]

        return results

    def to_actors_query(
        self, interval: Optional[int] = None, breakdown_values: str | list[str] | int | None = None
    ) -> ast.SelectQuery:
        with self.timings.measure("retention_actors_query"):
            # Cohort breakdowns require special handling as cohort breakdowns unlike say event breakdowns
            # run the original retention query for each cohort value separately and then combine the results
            # so while breaking down by cohort, we need to change the base query to only keep the cohort
            # for which we want to see the actors
            is_cohort_breakdown = (
                self.query.breakdownFilter is not None
                and self.query.breakdownFilter.breakdowns is not None
                and any(b.type == "cohort" for b in self.query.breakdownFilter.breakdowns)
            )

            base_query: ast.SelectQuery | ast.SelectSetQuery
            if is_cohort_breakdown:
                if not breakdown_values or not isinstance(breakdown_values, list) or len(breakdown_values) == 0:
                    raise ValueError("A cohort breakdown value is required for actors query with cohort breakdowns.")

                cohort_id = breakdown_values[0]
                temp_query = self.query.model_copy(deep=True)
                if temp_query.breakdownFilter:
                    temp_query.breakdownFilter.breakdowns = [Breakdown(type="cohort", property=int(cohort_id))]
                    # these are passed to the new runner to correctly construct the query
                    temp_query.breakdownFilter.breakdown = cohort_id
                    temp_query.breakdownFilter.breakdown_type = BreakdownType.COHORT

                runner = RetentionQueryRunner(
                    query=temp_query, team=self.team, timings=self.timings, modifiers=self.modifiers
                )
                base_query = runner.base_query(start_interval_index_filter=interval)

            else:
                selected_breakdown_value = None
                if breakdown_values:
                    if not isinstance(breakdown_values, list):
                        raise ValueError(
                            "Single breakdowns are not supported, ensure multiple-breakdowns feature flag is enabled"
                        )
                    selected_breakdown_value = "::".join(breakdown_values)

                base_query = self.base_query(
                    start_interval_index_filter=interval, selected_breakdown_value=selected_breakdown_value
                )

            # Build the retention actors query
            retention_query = parse_select(
                """
                    SELECT
                        actor_id,
                        groupArray(actor_activity.intervals_from_base) AS appearance_intervals,
                        arraySort(appearance_intervals) AS appearances

                    FROM {base_query} AS actor_activity

                    GROUP BY actor_id
                """,
                placeholders={
                    "base_query": base_query,
                },
                timings=self.timings,
            )
            assert isinstance(retention_query, ast.SelectQuery)

            # Add interval columns
            for i in range(self.lookahead_period_count):
                retention_query.select.append(
                    ast.Alias(
                        alias=f"{self.query_date_range.interval_name}_{i}",
                        expr=ast.Call(
                            name="arrayExists",
                            args=[
                                ast.Lambda(
                                    args=["x"],
                                    expr=ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["x"]),
                                        right=ast.Constant(value=i),
                                    ),
                                ),
                                ast.Field(chain=["appearance_intervals"]),
                            ],
                        ),
                    )
                )

        return retention_query

    def to_events_query(
        self, interval: int, breakdown_value: str | list[str] | int | None = None, person_id: str | None = None
    ) -> ast.SelectQuery:
        """
        Returns a query that gets all events (both start and return) that match for a specific interval and optional person.
        These events are the ones that contribute to the 'counts' for the respective interval.

        Args:
            interval: The interval index to get events for
            person_id: Optional person ID to filter events for

        Returns:
            A HogQL query that returns matching events
        """
        with self.timings.measure("events_retention_query"):
            # Calculate start and lookahead dates for the interval
            interval_start = self.query_date_range.date_from() + self.query_date_range.determine_time_delta(
                interval, self.query_date_range.interval_name.title()
            )

            lookahead_end = interval_start + self.query_date_range.determine_time_delta(
                self.query_date_range.lookahead, self.query_date_range.interval_name.title()
            )

            # Create subquery to identify qualified actors for this interval
            where_clauses: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["start_interval_index"]),
                    right=ast.Constant(value=interval),
                )
            ]

            if person_id is not None:
                where_clauses.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["actor_id"]),
                        right=ast.Constant(value=person_id),
                    )
                )

            actor_subquery = cast(
                ast.SelectQuery,
                parse_select(
                    """
                SELECT
                    actor_id,
                    start_interval_index,
                    intervals_from_base
                FROM
                    {base_query}
                """,
                    {
                        "base_query": self.base_query(
                            selected_breakdown_value=breakdown_value,
                            start_interval_index_filter=interval,
                        ),
                    },
                ),
            )

            actor_subquery.where = ast.And(exprs=where_clauses)
            # Common conditions from events_where_clause
            event_filters = self.events_where_clause(
                self.is_first_occurrence_matching_filters, self.is_first_ever_occurrence
            )

            # The event query will join actors with their events
            events_query = cast(
                ast.SelectQuery,
                parse_select(
                    """
                SELECT
                    events.timestamp as 'timestamp',
                    events.event as 'event',
                    events.person_id as 'person_id',
                    events.properties as 'properties',
                    {start_of_interval_sql} AS interval_timestamp,
                    multiIf(
                        -- Start events are those that occur in the start interval and match start entity
                        events.timestamp >= {interval_start} AND
                        events.timestamp < {interval_next} AND
                        {start_entity_expr},
                        'start_event',
                        -- Return events are those that occur in later intervals and match return entity
                        events.timestamp >= {interval_next} AND
                        events.timestamp < {lookahead_end} AND
                        {return_entity_expr},
                        'return_event',
                        NULL
                    ) AS event_type,
                    actors.intervals_from_base,
                    events.uuid as 'uuid',
                    events.distinct_id as 'distinct_id',
                    events.team_id,
                    events.elements_chain as 'elements_chain',
                    events.created_at as 'created_at'
                FROM
                    events
                JOIN
                    {actor_subquery} AS actors
                ON
                    {join_condition}
                WHERE
                    -- Only return events within the relevant time range
                    events.timestamp >= {interval_start} AND
                    events.timestamp < {lookahead_end} AND
                    -- Only include start and return events
                    (
                        (
                            events.timestamp >= {interval_start} AND
                            events.timestamp < {interval_next} AND
                            {start_entity_expr}
                        ) OR (
                            events.timestamp >= {interval_next} AND
                            events.timestamp < {lookahead_end} AND
                            {return_entity_expr}
                        )
                    )
                ORDER BY
                    events.timestamp
                """,
                    {
                        "actor_subquery": actor_subquery,
                        "join_condition": ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["events", self.aggregation_target_events_column]),
                            right=ast.Field(chain=["actors", "actor_id"]),
                        ),
                        "start_of_interval_sql": self.query_date_range.get_start_of_interval_hogql(
                            source=ast.Field(chain=["events", "timestamp"])
                        ),
                        "interval_start": ast.Constant(value=interval_start),
                        "interval_next": ast.Constant(
                            value=interval_start
                            + self.query_date_range.determine_time_delta(1, self.query_date_range.interval_name.title())
                        ),
                        "lookahead_end": ast.Constant(value=lookahead_end),
                        "start_entity_expr": entity_to_expr(self.start_event, self.team),
                        "return_entity_expr": entity_to_expr(self.return_event, self.team),
                    },
                    timings=self.timings,
                ),
            )

            # Add additional filters if they exist
            if event_filters:
                existing_where = events_query.where
                events_query.where = ast.And(exprs=[cast(ast.Expr, existing_where), ast.And(exprs=event_filters)])

            return events_query
