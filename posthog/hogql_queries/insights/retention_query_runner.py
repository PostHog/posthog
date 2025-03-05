from datetime import datetime, timedelta
from posthog.hogql.property import property_to_expr
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.constants import HogQLGlobalSettings, MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY
from math import ceil
from typing import Any, Optional

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
from posthog.schema import RetentionQuery, RetentionType

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

    @property
    def group_type_index(self) -> int | None:
        return self.query.aggregation_group_type_index

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

    def _get_events_for_entity(self, entity: RetentionEntity) -> list[str | None]:
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
        events = self._get_events_for_entity(self.start_event) + self._get_events_for_entity(self.return_event)
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

    def actor_query(
        self, start_interval_index_filter: Optional[int] = None, cumulative: bool = False
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
        global_event_filters = self.events_where_clause(event_query_type)

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
                                ast.Array(exprs=[ast.Constant(value="")]),  # TODO figure out why this is needed
                                ast.Field(chain=["events", f"$group_{self.group_type_index}"]),
                            ],
                        ),
                    ),
                )

        intervals_from_base_array_aggregator = "arrayJoin"
        if cumulative:
            intervals_from_base_array_aggregator = "arrayMax"

        # Build the base inner query WITHOUT breakdown fields yet
        inner_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor_id", expr=ast.Field(chain=["events", target_field])),
                # start events between date_from and date_to (represented by start of interval)
                # when TARGET_FIRST_TIME, also adds filter for start (target) event performed for first time
                ast.Alias(alias="start_event_timestamps", expr=start_event_timestamps),
                # return events between date_from and date_to (represented by start of interval)
                ast.Alias(
                    alias="return_event_timestamps",
                    expr=parse_expr(
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
                            "returning_entity_expr": entity_to_expr(self.return_event, self.team),
                            "filter_timestamp": self.events_timestamp_filter,
                        },
                    ),
                ),
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
            having=(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["start_interval_index"]),
                    right=ast.Constant(value=start_interval_index_filter),
                )
                # filter for specific interval (in case of actors popup)
                if start_interval_index_filter is not None
                else None
            ),
        )
        if self.query.samplingFactor is not None and isinstance(self.query.samplingFactor, float):
            inner_query.select_from.sample = ast.SampleExpr(
                sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))
            )

        # Add breakdown fields to the inner query where events table is accessible
        breakdown_props = []
        if self.query.breakdownFilter:
            if self.query.breakdownFilter.breakdowns and len(self.query.breakdownFilter.breakdowns) > 0:
                for i, breakdown in enumerate(self.query.breakdownFilter.breakdowns):
                    prop_expr = self._create_breakdown_expr(
                        breakdown.property, breakdown.type, breakdown.group_type_index
                    )
                    inner_query.select.append(ast.Alias(alias=f"breakdown_prop_{i}", expr=prop_expr))
                    breakdown_props.append(f"breakdown_prop_{i}")
            elif self.query.breakdownFilter.breakdown is not None:
                prop_expr = self._create_breakdown_expr(
                    self.query.breakdownFilter.breakdown,
                    self.query.breakdownFilter.breakdown_type,
                    getattr(self.query.breakdownFilter, "breakdown_group_type_index", None),
                )
                inner_query.select.append(ast.Alias(alias="breakdown_prop_0", expr=prop_expr))
                breakdown_props.append("breakdown_prop_0")

            # update group by to include breakdown props
            for prop in breakdown_props:
                inner_query.group_by.append(ast.Field(chain=[prop]))

        # Create the final breakdown value field (concatenation for multiple props)
        if breakdown_props:
            final_query = ast.SelectQuery(
                select=[
                    *[ast.Alias(alias=col.alias, expr=ast.Field(chain=[col.alias])) for col in inner_query.select],
                ],
                select_from=ast.JoinExpr(table=inner_query),
            )

            if len(breakdown_props) > 1:
                # Build concatenation for multiple breakdowns
                concat_expr = self._build_concat_expr([ast.Field(chain=[prop]) for prop in breakdown_props])
                final_query.select.append(ast.Alias(alias="breakdown_value", expr=concat_expr))
            else:
                # Use the single breakdown directly
                final_query.select.append(
                    ast.Alias(alias="breakdown_value", expr=ast.Field(chain=[breakdown_props[0]]))
                )

            return final_query

        return inner_query

    def _create_breakdown_expr(self, property_name, breakdown_type, group_type_index=None):
        """Create a breakdown expression that works in the innermost query level"""
        if breakdown_type == "person":
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=["person", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )
        elif breakdown_type == "group":
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=[f"groups_{group_type_index}", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )
        else:  # Default to event properties
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=["events", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )

    def _build_concat_expr(self, fields):
        """Build a concatenation expression with separators between fields"""
        if not fields:
            return ast.Constant(value="")

        components = []
        for i, field in enumerate(fields):
            components.append(field)
            if i < len(fields) - 1:
                components.append(ast.Constant(value="::"))

        # Build the expression with proper concatenation
        expr = components[0]
        for i in range(1, len(components), 2):
            expr = ast.BinaryOperation(
                left=expr,
                op=ast.BinaryOperationOp.Concat,
                right=ast.BinaryOperation(
                    left=components[i],
                    op=ast.BinaryOperationOp.Concat,
                    right=components[i + 1] if i + 1 < len(components) else ast.Constant(value=""),
                ),
            )

        return expr

    def breakdowns_in_query(self) -> bool:
        return self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        )

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
            if self.breakdowns_in_query():
                actor_query = self._add_breakdown_to_query(actor_query)

                # Build retention query with breakdown
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
                # Original retention query without breakdowns
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

    def get_date(self, interval: int):
        date = self.query_date_range.date_from() + self.query_date_range.determine_time_delta(
            interval, self.query_date_range.interval_name.title()
        )

        if self.query_date_range.interval_type == IntervalType.HOUR:
            utfoffset = self.team.timezone_info.utcoffset(date)
            if utfoffset is not None:
                date = date + utfoffset

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

        # Process results based on whether we have breakdowns
        if self.breakdowns_in_query():
            # Group results by breakdown_value
            breakdown_results = {}
            for row in response.results:
                if len(row) == 4:  # With breakdown: start_interval, intervals_from_base, breakdown_value, count
                    start_interval, intervals_from_base, breakdown_value, count = row

                    if breakdown_value not in breakdown_results:
                        breakdown_results[breakdown_value] = []

                    breakdown_results[breakdown_value].append((start_interval, intervals_from_base, count))

            # Format results for each breakdown
            results = []
            for breakdown_value, intervals in breakdown_results.items():
                # Create result dict for this breakdown
                result_dict = {
                    (start_interval, intervals_from_base): {
                        "count": correct_result_for_sampling(count, self.query.samplingFactor),
                    }
                    for (start_interval, intervals_from_base, count) in intervals
                }

                # Format results for this breakdown

                breakdown_results = [
                    {
                        "values": [
                            result_dict.get((start_interval, return_interval), {"count": 0})
                            for return_interval in range(self.query_date_range.lookahead)
                        ],
                        "label": f"{self.query_date_range.interval_name.title()} {start_interval}",
                        "date": self.get_date(start_interval),
                        "breakdown_value": breakdown_value,
                    }
                    for start_interval in range(self.query_date_range.intervals_between)
                ]

                results.extend(breakdown_results)
        else:
            # Standard non-breakdown results processing
            result_dict = {
                (start_event_matching_interval, intervals_from_base): {
                    "count": correct_result_for_sampling(count, self.query.samplingFactor),
                }
                for (start_event_matching_interval, intervals_from_base, count) in response.results
            }
            results = [
                {
                    "values": [
                        result_dict.get((start_interval, return_interval), {"count": 0})
                        for return_interval in range(self.query_date_range.lookahead)
                    ],
                    "label": f"{self.query_date_range.interval_name.title()} {start_interval}",
                    "date": self.get_date(start_interval),
                }
                for start_interval in range(self.query_date_range.intervals_between)
            ]

        return RetentionQueryResponse(results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers)

    def to_actors_query(self, interval: Optional[int] = None, breakdown_value: Optional[str] = None) -> ast.SelectQuery:
        with self.timings.measure("retention_query"):
            # Get base actor query
            actor_query = self.actor_query(start_interval_index_filter=interval)

            # Add breakdown filtering if needed
            if breakdown_value is not None and self.query.breakdownFilter:
                # Always treat breakdowns as multiple breakdowns
                breakdown_fields = []

                if self.query.breakdownFilter.breakdowns and len(self.query.breakdownFilter.breakdowns) > 0:
                    for breakdown in self.query.breakdownFilter.breakdowns:
                        field = self._get_breakdown_expr(breakdown.property, breakdown.type, breakdown.group_type_index)
                        breakdown_fields.append(field)
                elif self.query.breakdownFilter.breakdown is not None:
                    field = self._get_breakdown_expr(
                        self.query.breakdownFilter.breakdown, self.query.breakdownFilter.breakdown_type
                    )
                    breakdown_fields.append(field)

                # Create breakdown expression
                if len(breakdown_fields) > 1:
                    # Build concatenation expression with || operators
                    expr = ast.Call(name="toString", args=[breakdown_fields[0]])
                    for field in breakdown_fields[1:]:
                        separator = ast.Constant(value="::")
                        field_str = ast.Call(name="toString", args=[field])
                        # Create chained concatenation: expr || '::' || toString(field)
                        expr = ast.BinaryOperation(
                            left=expr,
                            op=ast.BinaryOperationOp.Concat,
                            right=ast.BinaryOperation(left=separator, op=ast.BinaryOperationOp.Concat, right=field_str),
                        )
                    breakdown_expr = expr
                else:
                    breakdown_expr = breakdown_fields[0]

                # Add breakdown to query and filter by value
                actor_query = parse_select(
                    """
                    SELECT * FROM (
                        SELECT
                            *,
                            {breakdown_expr} AS breakdown_value
                        FROM {actor_query}
                    ) WHERE breakdown_value = {breakdown_value}
                    """,
                    {
                        "actor_query": actor_query,
                        "breakdown_expr": breakdown_expr,
                        "breakdown_value": ast.Constant(value=breakdown_value),
                    },
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

    def _add_breakdown_to_query(self, actor_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Adds breakdown fields to the actor query.
        This method is called in to_query() and needs proper implementation.
        """
        # If there are no breakdown filters, return the original query
        if not self.query.breakdownFilter:
            return actor_query

        # At this level we can't access the raw events table anymore
        # We need to reference fields that were already selected in actor_query

        # We'll need to modify our actor_query at this point to include the breakdown value
        # Since we've already added breakdown fields in actor_query() method at the inner level,
        # we can just reference those fields directly

        # Create a new query that selects from actor_query
        new_query = ast.SelectQuery(
            select=[
                # Include all existing columns
                ast.Alias(alias=col.alias, expr=col.expr)
                for col in actor_query.select
            ],
            select_from=ast.JoinExpr(table=actor_query),
        )

        return new_query

    def _get_breakdown_expr(self, property_name, breakdown_type, group_type_index=None):
        """Similar to _create_breakdown_expr but for actors query"""
        if breakdown_type == "person":
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=["person", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )
        elif breakdown_type == "group":
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=[f"groups_{group_type_index}", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )
        else:  # Default to event properties
            return ast.Call(
                name="JSONExtractString",
                args=[
                    ast.Field(chain=["events", "properties"]),
                    ast.Constant(value=property_name),
                ],
            )
