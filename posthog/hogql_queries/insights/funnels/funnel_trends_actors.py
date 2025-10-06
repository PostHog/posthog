from datetime import datetime

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnel_trends import FunnelTrends
from posthog.utils import relative_date_parse


class FunnelTrendsActors(FunnelTrends):
    entrancePeriodStart: datetime
    dropOff: bool

    def __init__(self, context: FunnelQueryContext, just_summarize=False):
        super().__init__(context, just_summarize)

        team, actorsQuery = self.context.team, self.context.actorsQuery

        if actorsQuery is None:
            raise ValidationError("No actors query present.")

        if actorsQuery.funnelTrendsDropOff is None:
            raise ValidationError(f"Actors parameter `funnelTrendsDropOff` must be provided for funnel trends persons!")

        if actorsQuery.funnelTrendsEntrancePeriodStart is None:
            raise ValidationError(
                f"Actors parameter `funnelTrendsEntrancePeriodStart` must be provided funnel trends persons!"
            )

        entrancePeriodStart = relative_date_parse(actorsQuery.funnelTrendsEntrancePeriodStart, team.timezone_info)
        if entrancePeriodStart is None:
            raise ValidationError(
                f"Actors parameter `funnelTrendsEntrancePeriodStart` must be a valid relative date string!"
            )

        self.dropOff = actorsQuery.funnelTrendsDropOff
        self.entrancePeriodStart = entrancePeriodStart

    def _get_funnel_person_step_events(self) -> list[ast.Expr]:
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            # Get the event that should be used to match the recording
            funnel_to_step = self.context.funnelsFilter.funnelToStep
            is_drop_off = self.dropOff

            if funnel_to_step is None or is_drop_off:
                # If there is no funnel_to_step or if we are looking for drop off, we need to get the users final event
                return [ast.Alias(alias="matching_events", expr=ast.Field(chain=["final_matching_events"]))]
            else:
                # Otherwise, we return the event of the funnel_to_step
                return [
                    ast.Alias(alias="matching_events", expr=ast.Field(chain=[f"step_{funnel_to_step}_matching_events"]))
                ]
        return []

    def actor_query(self, *args) -> ast.SelectQuery:
        step_counts_query = self.get_step_counts_without_aggregation_query(
            specific_entrance_period_start=self.entrancePeriodStart
        )

        # Expects multiple rows for same person, first event time, steps taken.
        (
            _,
            reached_to_step_count_condition,
            did_not_reach_to_step_count_condition,
        ) = self.get_steps_reached_conditions()

        select: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["aggregation_target"])),
            *self._get_funnel_person_step_events(),
        ]
        select_from = ast.JoinExpr(table=step_counts_query)
        where = (
            parse_expr(did_not_reach_to_step_count_condition)
            if self.dropOff
            else parse_expr(reached_to_step_count_condition)
        )
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
        )
