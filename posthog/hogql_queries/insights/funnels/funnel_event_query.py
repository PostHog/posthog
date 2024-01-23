from typing import List, Optional, Set, Union
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.utils.properties import Properties
from posthog.models.action.action import Action
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, FunnelsQuery, HogQLQueryModifiers
from rest_framework.exceptions import ValidationError


class FunnelEventQuery(FunnelQueryContext):
    EVENT_TABLE_ALIAS = "e"

    def __init__(
        self,
        query: FunnelsQuery,
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)

    def to_query(
        self,
        # entities=None, # TODO: implement passed in entities when needed
        skip_entity_filter=False,
    ) -> ast.SelectQuery:
        select: List[ast.Expr] = [
            ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
            ast.Alias(alias="aggregation_target", expr=ast.Field(chain=[self._aggregation_target_column()])),
        ]

        select_from = ast.JoinExpr(
            table=ast.Field(chain=["events"]),
            alias=self.EVENT_TABLE_ALIAS,
            sample=self._sample_expr(),
        )

        where_exprs = [self._date_range_expr(), self._entity_expr(skip_entity_filter), self._properties_expr()]
        where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

        stmt = ast.SelectQuery(
            select=select,
            select_from=select_from,
            where=where,
        )
        return stmt

    def _aggregation_target_column(self) -> str:
        # Aggregating by group
        if self.query.aggregation_group_type_index is not None:
            aggregation_target = f'{self.EVENT_TABLE_ALIAS}."$group_{self.query.aggregation_group_type_index}"'

        # Aggregating by HogQL
        elif self.funnelsFilter.funnelAggregateByHogQL and self.funnelsFilter.funnelAggregateByHogQL != "person_id":
            aggregation_target = translate_hogql(
                self.funnelsFilter.funnelAggregateByHogQL,
                events_table_alias=self.EVENT_TABLE_ALIAS,
                context=self.hogql_context,
            )

        # TODO: is this still relevant?
        # # Aggregating by Distinct ID
        # elif self._aggregate_users_by_distinct_id:
        #     aggregation_target = f"{self.EVENT_TABLE_ALIAS}.distinct_id"

        # Aggregating by Person ID
        else:
            aggregation_target = "person_id"

        return aggregation_target

    def _sample_expr(self) -> ast.SampleExpr | None:
        if self.query.samplingFactor is None:
            return None
        else:
            return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor)))

    def _date_range_expr(self) -> ast.Expr:
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"]),
                    right=ast.Constant(value=self.query_date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"]),
                    right=ast.Constant(value=self.query_date_range.date_to()),
                ),
            ]
        )

    def _entity_expr(self, skip_entity_filter: bool) -> ast.Expr | None:
        if skip_entity_filter is True:
            return None

        events: Set[Union[int, str, None]] = set()

        for node in self.query.series:
            if isinstance(node, EventsNode):
                events.add(node.event)
            elif isinstance(node, ActionsNode):
                action = Action.objects.get(pk=int(node.id), team=self.team)
                events.add(action.name)
            else:
                raise ValidationError("Series must either be events or actions")

        # Disable entity pre-filtering for "All events"
        if None in events:
            return None

        return ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            right=ast.Tuple(exprs=[ast.Constant(value=event) for event in events]),
            op=ast.CompareOperationOp.In,
        )

    def _properties_expr(self) -> List[ast.Expr]:
        return Properties(
            team=self.team, properties=self.query.properties, filterTestAccounts=self.query.filterTestAccounts
        ).to_exprs()
