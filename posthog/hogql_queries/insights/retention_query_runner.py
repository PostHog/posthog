from datetime import datetime, timedelta

from posthog.hogql.ast import Alias
from posthog.hogql.base import Expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.constants import HogQLGlobalSettings, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
from math import ceil
from typing import Any, cast, Optional

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.constants import (
    TREND_FILTER_TYPE_EVENTS,
    RetentionQueryType,
)
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import entity_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models.action.action import Action
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.util import correct_result_for_sampling
from posthog.schema import (
    CachedRetentionQueryResponse,
    HogQLQueryModifiers,
    RetentionQueryResponse,
    IntervalType,
    RetentionEntity,
    EntityType,
)
from posthog.schema import RetentionQuery, RetentionType, Breakdown
from posthog.hogql.constants import get_breakdown_limit_for_context
from posthog.hogql_queries.insights.trends.breakdown import BREAKDOWN_OTHER_STRING_LABEL

DEFAULT_INTERVAL = IntervalType("day")
DEFAULT_TOTAL_INTERVALS = 7

DEFAULT_ENTITY = RetentionEntity(
    **{
        "id": "$pageview",
        "type": TREND_FILTER_TYPE_EVENTS,
    }
)


class RetentionQueryRunner(QueryRunner):
    query: RetentionQuery
    response: RetentionQueryResponse
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
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

        self.start_event = self.query.retentionFilter.targetEntity or DEFAULT_ENTITY
        self.return_event = self.query.retentionFilter.returningEntity or DEFAULT_ENTITY

        self.convert_single_breakdown_to_multiple_breakdowns()

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

    def convert_single_breakdown_to_multiple_breakdowns(self):
        if self.query.breakdownFilter and self.query.breakdownFilter.breakdown:
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
        return self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        )

    @cached_property
    def events_timestamp_filter(self) -> ast.Expr:
        """
        Timestamp filter between date_from and date_to
        """
        field_to_compare = ast.Field(chain=["events", "timestamp"])
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
        intervals_to_look_ahead = self.query.retentionFilter.totalIntervals or DEFAULT_TOTAL_INTERVALS
        interval = (
            IntervalType(self.query.retentionFilter.period.lower())
            if self.query.retentionFilter.period
            else DEFAULT_INTERVAL
        )

        return QueryDateRangeWithIntervals(
            date_range=self.query.dateRange,
            total_intervals=intervals_to_look_ahead,
            team=self.team,
            interval=interval,
            now=datetime.now(),
        )

    def get_events_for_entity(self, entity: RetentionEntity) -> list[str | None]:
        if entity.type == EntityType.ACTIONS and entity.id:
            action = Action.objects.get(pk=int(entity.id), team__project_id=self.team.project_id)
            return action.get_step_events()
        return [entity.id] if isinstance(entity.id, str) else [None]

    def events_where_clause(self, event_query_type: RetentionQueryType):
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

        if event_query_type == RetentionQueryType.TARGET:
            # when it's recurring, we only have to grab events for the period, rather than events for all time
            events_where.append(self.events_timestamp_filter)

        # Pre filter event
        events = self.get_events_for_entity(self.start_event) + self.get_events_for_entity(self.return_event)
        # Don't pre-filter if any of them is "All events"
        if None not in events:
            events_where.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    # Sorting for consistent snapshots in tests
                    right=ast.Tuple(exprs=[ast.Constant(value=event) for event in sorted(events)]),  # type: ignore
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

    def breakdown_extract_expr(
        self, property_name: str, breakdown_type: str, group_type_index: int | None = None
    ) -> ast.Expr:
        if breakdown_type == "person":
            if property_name.startswith("$virt_"):
                # Virtual properties exist as expression fields on the persons table
                properties_chain = ["person", property_name]
            else:
                properties_chain = ["person", "properties", property_name]
        elif breakdown_type == "group":
            properties_chain = [f"groups_{group_type_index}", "properties", property_name]
        else:
            # Default to event properties
            properties_chain = ["events", "properties", property_name]

        # Convert the property to String first, then handle NULLs.
        # This avoids potential type mismatches (e.g., mixing Float64 and String for NULLs).
        property_field = ast.Field(chain=cast(list[str | int], properties_chain))
        to_string_expr = ast.Call(name="toString", args=[property_field])
        # Replace NULL with empty string ''
        return ast.Call(name="ifNull", args=[to_string_expr, ast.Constant(value="")])

    def actor_query(
        self,
        cumulative: bool = False,
        start_interval_index_filter: Optional[int] = None,
        selected_breakdown_value: str | list[str] | int | None = None,
    ) -> ast.SelectQuery:
        start_of_interval_sql = self.query_date_range.get_start_of_interval_hogql(
            source=ast.Field(chain=["events", "timestamp"])
        )

        event_query_type = (
            RetentionQueryType.TARGET_FIRST_TIME
            if self.query.retentionFilter.retentionType == RetentionType.RETENTION_FIRST_TIME
            else RetentionQueryType.TARGET
        )

        start_entity_expr = entity_to_expr(self.start_event, self.team)
        return_entity_expr = entity_to_expr(self.return_event, self.team)
        global_event_filters = self.events_where_clause(event_query_type)

        # Pre-filter events to only those we care about
        is_relevant_event = ast.Or(exprs=[start_entity_expr, return_entity_expr])
        global_event_filters.append(is_relevant_event)

        start_event_timestamps = parse_expr(
            """
            arraySort(
                groupUniqArrayIf(
                    {start_of_interval_sql},
                    {start_entity_expr} and
                    {filter_timestamp}
                )
            )
            """,
            {
                "start_of_interval_sql": start_of_interval_sql,
                "start_entity_expr": start_entity_expr,
                "filter_timestamp": self.events_timestamp_filter,
            },
        )

        minimum_occurrences = self.query.retentionFilter.minimumOccurrences or 1
        minimum_occurrences_aliases = self._get_minimum_occurrences_aliases(
            minimum_occurrences=minimum_occurrences,
            start_of_interval_sql=start_of_interval_sql,
            return_entity_expr=return_entity_expr,
        )
        return_event_timestamps = self._get_return_event_timestamps_expr(
            minimum_occurrences=minimum_occurrences,
            start_of_interval_sql=start_of_interval_sql,
            return_entity_expr=return_entity_expr,
        )

        if event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            start_event_timestamps = parse_expr(
                """
                    if(
                        has(
                            {start_event_timestamps} as _start_event_timestamps,
                            {min_timestamp}
                        ),
                        _start_event_timestamps,
                        []
                    )
                """,
                {
                    "start_event_timestamps": start_event_timestamps,
                    # cast this to start of interval as well so we can compare with the timestamps fetched above
                    "min_timestamp": self.query_date_range.date_to_start_of_interval_hogql(
                        parse_expr(
                            "minIf(events.timestamp, {start_entity_expr})",
                            {
                                "start_entity_expr": start_entity_expr,
                            },
                        )
                    ),
                },
            )
            # interval must be same as first interval of in which start event happened
            is_valid_start_interval = parse_expr("start_event_timestamps[1] = interval_date")
            is_first_interval_after_start_event = parse_expr(
                "start_event_timestamps[1] = date_range[start_interval_index + 1]"
            )
        else:
            # start event must have happened in the interval
            is_valid_start_interval = parse_expr("has(start_event_timestamps, interval_date)")
            is_first_interval_after_start_event = parse_expr(
                "has(start_event_timestamps, date_range[start_interval_index + 1])"
            )

        target_field = "person_id"
        if self.group_type_index is not None:
            group_index = int(self.group_type_index)
            if 0 <= group_index <= 4:
                target_field = f"$group_{group_index}"

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

        intervals_from_base_array_aggregator = "arrayJoin"
        if cumulative:
            intervals_from_base_array_aggregator = "arrayMax"

        inner_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", target_field])),
                # start events between date_from and date_to (represented by start of interval)
                # when TARGET_FIRST_TIME, also adds filter for start (target) event performed for first time
                ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps),
                # get all intervals between date_from and date_to (represented by start of interval)
                ast.Alias(
                    alias="date_range",
                    expr=parse_expr(
                        """
                        arrayMap(
                            x -> {date_from_start_of_interval} + {to_interval_function},
                            range(0, {intervals_between})
                        )
                    """,
                        {
                            "intervals_between": ast.Constant(value=self.query_date_range.intervals_between),
                            "date_from_start_of_interval": self.query_date_range.date_from_to_start_of_interval_hogql(),
                            "to_interval_function": ast.Call(
                                name=f"toInterval{self.query_date_range.interval_name.capitalize()}",
                                args=[ast.Field(chain=["x"])],
                            ),
                        },
                    ),
                ),
                *minimum_occurrences_aliases,
                # timestamps representing the start of a qualified interval (where count of events >= minimum_occurrences)
                ast.Alias(alias="return_event_timestamps", expr=return_event_timestamps),
                # exploded (0 based) indices of matching intervals for start event
                ast.Alias(
                    alias="start_interval_index",
                    expr=parse_expr(
                        """
                        arrayJoin(
                            arrayFilter(
                                x -> x > -1,
                                arrayMap(
                                (interval_index, interval_date) ->
                                    if(
                                        {is_valid_start_interval},
                                        interval_index - 1,
                                        -1
                                    ),
                                    arrayEnumerate(date_range),
                                    date_range
                                )
                            )
                        )
                    """,
                        {"is_valid_start_interval": is_valid_start_interval},
                    ),
                ),
                ast.Alias(
                    alias="intervals_from_base",
                    expr=parse_expr(
                        f"""
                    {intervals_from_base_array_aggregator}(
                        arrayConcat(
                            if(
                                {{is_first_interval_after_start_event}},
                                [0],
                                []
                            ),
                            arrayFilter(  -- index (time lag starting from start event) of interval with matching return timestamp
                                x -> x > 0, -- has to be at least one interval after start event (hence 0 and not -1 here)
                                arrayMap(
                                    _timestamp ->
                                        indexOf(
                                            arraySlice(  -- only look for matches for return events after start event and in the lookahead period
                                                date_range,
                                                start_interval_index + 1,  -- reset from 0 to 1 based index
                                                {self.query_date_range.lookahead}
                                            ),
                                        _timestamp
                                    ) - 1,
                                    return_event_timestamps
                                )
                            )
                        )
                    )
                    """,
                        {
                            "is_first_interval_after_start_event": is_first_interval_after_start_event,
                        },
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=global_event_filters),
            group_by=[ast.Field(chain=["actor_id"])],
            having=ast.And(
                exprs=[
                    (
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["start_interval_index"]),
                            right=ast.Constant(value=start_interval_index_filter),
                        )
                        if start_interval_index_filter is not None
                        else ast.Constant(value=1)
                    ),
                    (
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["breakdown_value"]),
                            right=ast.Constant(value=selected_breakdown_value),
                        )
                        if selected_breakdown_value is not None
                        else ast.Constant(value=1)
                    ),
                ]
            ),
        )

        if (
            self.query.samplingFactor is not None
            and isinstance(self.query.samplingFactor, float)
            and inner_query.select_from is not None
        ):
            inner_query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        if self.query.breakdownFilter:
            if self.query.breakdownFilter.breakdowns:
                # supporting only single breakdowns for now
                breakdown = self.query.breakdownFilter.breakdowns[0]
                breakdown_expr = self.breakdown_extract_expr(
                    breakdown.property, cast(str, breakdown.type), breakdown.group_type_index
                )

                # update both select and group by
                inner_query.select.append(ast.Alias(alias="breakdown_value", expr=breakdown_expr))
                cast(list[ast.Expr], inner_query.group_by).append(ast.Field(chain=["breakdown_value"]))
            elif self.query.breakdownFilter.breakdown is not None:
                raise ValueError(
                    "Single breakdowns are deprecated, make sure multiple-breakdowns feature flag is enabled"
                )

        return inner_query

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        with self.timings.measure("retention_query"):
            if self.query.retentionFilter.cumulative:
                actor_query = parse_select(
                    """
                    SELECT
                        actor_id,
                        arrayJoin(range(0, intervals_from_base + 1)) as intervals_from_base,
                        start_interval_index
                    FROM {actor_query}
                    """,
                    {"actor_query": self.actor_query(cumulative=True)},
                )
            else:
                actor_query = self.actor_query()

            # Add breakdown if needed
            if self.breakdowns_in_query:
                retention_query = parse_select(
                    """
                    SELECT
                        actor_activity.start_interval_index AS start_event_matching_interval,
                        actor_activity.intervals_from_base AS intervals_from_base,
                        actor_activity.breakdown_value AS breakdown_value,
                        COUNT(DISTINCT actor_activity.actor_id) AS count

                    FROM {actor_query} AS actor_activity

                    GROUP BY
                        start_event_matching_interval,
                        intervals_from_base,
                        breakdown_value

                    ORDER BY
                        breakdown_value,
                        start_event_matching_interval,
                        intervals_from_base

                    LIMIT 10000
                    """,
                    {"actor_query": actor_query},
                    timings=self.timings,
                )
            else:
                retention_query = parse_select(
                    """
                        SELECT actor_activity.start_interval_index     AS start_event_matching_interval,
                               actor_activity.intervals_from_base      AS intervals_from_base,
                               COUNT(DISTINCT actor_activity.actor_id) AS count

                        FROM {actor_query} AS actor_activity

                        GROUP BY start_event_matching_interval,
                                 intervals_from_base

                        ORDER BY start_event_matching_interval,
                                 intervals_from_base

                        LIMIT 10000
                    """,
                    {"actor_query": actor_query},
                    timings=self.timings,
                )
        return retention_query

    def get_date(self, interval: int):
        date = self.query_date_range.date_from() + self.query_date_range.determine_time_delta(
            interval, self.query_date_range.interval_name.title()
        )

        return date

    def calculate(self) -> RetentionQueryResponse:
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

        if self.breakdowns_in_query:
            # Step 1: Calculate total cohort size for each breakdown value (size at intervals_from_base = 0)
            breakdown_totals: dict[str, int] = {}
            original_results = response.results or []
            for row in original_results:
                start_interval, intervals_from_base, breakdown_value, count = row
                if intervals_from_base == 0:
                    breakdown_totals[breakdown_value] = breakdown_totals.get(breakdown_value, 0) + count

            # Step 2: Rank breakdowns and determine top N and 'Other'
            breakdown_limit = (
                self.query.breakdownFilter.breakdown_limit
                if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_limit is not None
                else get_breakdown_limit_for_context(self.limit_context)
            )
            # Sort by count descending, then by breakdown value ascending for stability
            sorted_breakdowns = sorted(breakdown_totals.items(), key=lambda item: (-item[1], item[0]), reverse=False)
            other_values = {item[0] for item in sorted_breakdowns[breakdown_limit:]}

            # Step 3: Aggregate results, grouping less frequent breakdowns into 'Other'
            aggregated_data: dict[str, dict[int, dict[int, float]]] = {}
            for row in original_results:
                start_interval, intervals_from_base, breakdown_value, count = row

                target_breakdown = breakdown_value
                if breakdown_value in other_values:
                    target_breakdown = BREAKDOWN_OTHER_STRING_LABEL

                # Apply sampling correction when aggregating into the final structure
                corrected_count = correct_result_for_sampling(count, self.query.samplingFactor)
                aggregated_data[target_breakdown] = aggregated_data.get(target_breakdown, {})
                breakdown_data = aggregated_data[target_breakdown]

                breakdown_data[start_interval] = breakdown_data.get(start_interval, {})
                interval_data = breakdown_data[start_interval]
                interval_data[intervals_from_base] = interval_data.get(intervals_from_base, 0.0) + corrected_count

            # Step 4: Format final output
            final_results: list[dict[str, Any]] = []
            # Keep track of the order based on the ranking
            ordered_breakdown_keys = [item[0] for item in sorted_breakdowns[:breakdown_limit]]
            if other_values:
                ordered_breakdown_keys.append(BREAKDOWN_OTHER_STRING_LABEL)

            for breakdown_value in ordered_breakdown_keys:
                intervals_data: dict[int, dict[int, float]] = aggregated_data.get(breakdown_value, {})

                breakdown_results = []
                for start_interval in range(self.query_date_range.intervals_between):
                    result_dict: dict[int, float] = intervals_data.get(start_interval, {})
                    values = [
                        {
                            "count": result_dict.get(return_interval, 0.0),
                            "label": f"{self.query_date_range.interval_name.title()} {return_interval}",
                        }
                        for return_interval in range(self.query_date_range.lookahead)
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
            # Rename this variable to avoid conflict with the one in the if block
            results_by_interval_pair: dict[tuple[int, int], dict[str, float]] = {
                (start_event_matching_interval, intervals_from_base): {
                    "count": correct_result_for_sampling(count, self.query.samplingFactor)
                }
                for (start_event_matching_interval, intervals_from_base, count) in response.results
            }
            results = [
                {
                    "values": [
                        {
                            **results_by_interval_pair.get((start_interval, return_interval), {"count": 0.0}),
                            "label": f"{self.query_date_range.interval_name.title()} {return_interval}",
                        }
                        for return_interval in range(self.query_date_range.lookahead)
                    ],
                    "label": f"{self.query_date_range.interval_name.title()} {start_interval}",
                    "date": self.get_date(start_interval),
                }
                for start_interval in range(self.query_date_range.intervals_between)
            ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers)

    def to_actors_query(
        self, interval: Optional[int] = None, breakdown_values: str | list[str] | int | None = None
    ) -> ast.SelectQuery:
        selected_breakdown_value = None

        if breakdown_values:
            if not isinstance(breakdown_values, list):
                raise ValueError(
                    "Single breakdowns are not supported, ensure multiple-breakdowns feature flag is enabled"
                )

            selected_breakdown_value = "::".join(breakdown_values)

        with self.timings.measure("retention_actors_query"):
            actor_query = self.actor_query(
                start_interval_index_filter=interval, selected_breakdown_value=selected_breakdown_value
            )

            # Build the retention actors query
            retention_query = parse_select(
                """
                    SELECT
                        actor_id,
                        groupArray(actor_activity.intervals_from_base) AS appearance_intervals,
                        arraySort(appearance_intervals) AS appearances

                    FROM {actor_query} AS actor_activity

                    GROUP BY actor_id
                """,
                placeholders={
                    "actor_query": actor_query,
                },
                timings=self.timings,
            )
            assert isinstance(retention_query, ast.SelectQuery)

            # Add interval columns
            for i in range(self.query_date_range.lookahead):
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
            # Get the target field based on group type
            target_field = "person_id"
            if self.group_type_index is not None:
                group_index = int(self.group_type_index)
                if 0 <= group_index <= 4:
                    target_field = f"$group_{group_index}"

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
                    {actor_query}
                """,
                    {
                        "actor_query": self.actor_query(
                            selected_breakdown_value=breakdown_value,
                            start_interval_index_filter=interval,
                        ),
                    },
                ),
            )

            actor_subquery.where = ast.And(exprs=where_clauses)

            # Create query that gets all relevant events for the matching actors
            event_query_type = (
                RetentionQueryType.TARGET_FIRST_TIME
                if self.query.retentionFilter.retentionType == RetentionType.RETENTION_FIRST_TIME
                else RetentionQueryType.TARGET
            )

            # Common conditions from events_where_clause
            event_filters = self.events_where_clause(event_query_type)

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
                            left=ast.Field(chain=["events", target_field]),
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

    def _get_return_event_timestamps_expr(
        self, minimum_occurrences: int, start_of_interval_sql: Expr, return_entity_expr: Expr
    ) -> Expr:
        if minimum_occurrences > 1:
            # return_event_counts_by_interval is only calculated when minimum_occurrences > 1.
            # See _get_minimum_occurrences_aliases method.
            return parse_expr(
                """
                arrayFilter(
                (date, counts) -> counts >= {minimum_occurrences},
                date_range,
                return_event_counts_by_interval,
                )
                """,
                {"minimum_occurrences": ast.Constant(value=minimum_occurrences)},
            )

        return parse_expr(
            """
                arraySort(
                    groupUniqArrayIf(
                        {start_of_interval_timestamp},
                        {returning_entity_expr} and
                        {filter_timestamp}
                    )
                )
            """,
            {
                "start_of_interval_timestamp": start_of_interval_sql,
                "returning_entity_expr": return_entity_expr,
                "filter_timestamp": self.events_timestamp_filter,
            },
        )

    def _get_minimum_occurrences_aliases(
        self, minimum_occurrences: int, start_of_interval_sql: Expr, return_entity_expr: Expr
    ) -> list[Alias]:
        """
        Only include the following expressions when minimum occurrences value is set and greater than one. The query
        with occurrences uses slightly more RAM, what can make some existing queries go over the max memory setting we
        have and having them stop working.
        """
        if minimum_occurrences == 1:
            return []

        return_event_timestamps_with_dupes = ast.Alias(
            alias="return_event_timestamps_with_dupes",
            expr=parse_expr(
                """
                groupArrayIf(
                    {start_of_interval_timestamp},
                    {returning_entity_expr} and
                    {filter_timestamp}
                )
                """,
                {
                    "start_of_interval_timestamp": start_of_interval_sql,
                    "returning_entity_expr": return_entity_expr,
                    "filter_timestamp": self.events_timestamp_filter,
                },
            ),
        )
        return_event_counts_by_interval = ast.Alias(
            alias="return_event_counts_by_interval",
            expr=parse_expr(
                """
                arrayMap(
                    interval_date -> countEqual(return_event_timestamps_with_dupes, interval_date),
                    date_range
                )
                """
            ),
        )
        return [return_event_timestamps_with_dupes, return_event_counts_by_interval]
