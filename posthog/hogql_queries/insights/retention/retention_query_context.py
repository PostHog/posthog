from datetime import datetime
from typing import cast

from posthog.schema import AggregationType, EntityType, IntervalType, RetentionEntity, RetentionQuery, RetentionType

from posthog.hogql import ast
from posthog.hogql.property import entity_to_expr, property_to_expr

from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.hogql_queries.insights.retention.utils import has_cohort_property
from posthog.hogql_queries.insights.utils.breakdowns import has_breakdown_filter
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.filters.mixins.utils import cached_property

DEFAULT_INTERVAL = IntervalType("day")
DEFAULT_TOTAL_INTERVALS = 7

DEFAULT_ENTITY = RetentionEntity(
    **{
        "id": "$pageview",
        "type": TREND_FILTER_TYPE_EVENTS,
    }
)


class RetentionQueryContext:
    query: RetentionQuery
    team: Team
    start_event: RetentionEntity
    return_event: RetentionEntity

    def __init__(self, query: RetentionQuery, team: Team) -> None:
        self.query = query
        self.team = team
        self.start_event = self.query.retentionFilter.targetEntity or DEFAULT_ENTITY
        self.return_event = self.query.retentionFilter.returningEntity or DEFAULT_ENTITY

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

    @cached_property
    def breakdowns_in_query(self) -> bool:
        return has_breakdown_filter(self.query.breakdownFilter)

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

    @cached_property
    def has_cohort_filter(self) -> bool:
        if self.query.properties and has_cohort_property(self.query.properties):
            return True

        if not self.query.breakdownFilter:
            return False

        return self.query.breakdownFilter.breakdown_type == "cohort" or (
            self.query.breakdownFilter.breakdowns is not None
            and any(b.type == "cohort" for b in self.query.breakdownFilter.breakdowns)
        )

    def get_events_for_entity(self, entity: RetentionEntity) -> list[str | None]:
        if entity.type == EntityType.ACTIONS and entity.id:
            action = Action.objects.get(pk=int(entity.id), team__project_id=self.team.project_id)
            return action.get_step_events()
        return [entity.id] if isinstance(entity.id, str) else [None]

    def events_where_clause(
        self, is_first_occurrence_matching_filters: bool, is_first_ever_occurrence: bool = False
    ) -> list[ast.Expr]:
        """
        Event filters to apply to both start and return events
        """
        events_where: list[ast.Expr] = []

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
            events_where.append(self.events_timestamp_filter)

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
