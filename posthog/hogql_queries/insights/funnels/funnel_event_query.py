from typing import List, Set, Union
from posthog.hogql import ast
from posthog.hogql.hogql import translate_hogql
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.date_range import DateRange
from posthog.hogql_queries.insights.utils.properties import Properties
from posthog.models.action.action import Action
from posthog.schema import ActionsNode, EventsNode
from rest_framework.exceptions import ValidationError


class FunnelEventQuery:
    context: FunnelQueryContext

    EVENT_TABLE_ALIAS = "e"

    def __init__(
        self,
        context: FunnelQueryContext,
    ):
        self.context = context

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

        where_exprs = [self._date_range_expr(), self._entity_expr(skip_entity_filter), *self._properties_expr()]
        where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

        stmt = ast.SelectQuery(
            select=select,
            select_from=select_from,
            where=where,
        )
        return stmt

    def _aggregation_target_column(self) -> str:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter

        # Aggregating by group
        if query.aggregation_group_type_index is not None:
            aggregation_target = f'{self.EVENT_TABLE_ALIAS}."$group_{query.aggregation_group_type_index}"'

        # Aggregating by HogQL
        elif funnelsFilter.funnelAggregateByHogQL and funnelsFilter.funnelAggregateByHogQL != "person_id":
            aggregation_target = translate_hogql(
                funnelsFilter.funnelAggregateByHogQL,
                events_table_alias=self.EVENT_TABLE_ALIAS,
                context=self.context.hogql_context,
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
        query = self.context.query

        if query.samplingFactor is None:
            return None
        else:
            return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=query.samplingFactor)))

    def _date_range_expr(self) -> ast.Expr:
        return DateRange(context=self.context).to_expr(field=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"]))

    def _entity_expr(self, skip_entity_filter: bool) -> ast.Expr | None:
        team, query = self.context.team, self.context.query

        if skip_entity_filter is True:
            return None

        events: Set[Union[int, str, None]] = set()

        for node in query.series:
            if isinstance(node, EventsNode):
                events.add(node.event)
            elif isinstance(node, ActionsNode):
                action = Action.objects.get(pk=int(node.id), team=team)
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
        return Properties(context=self.context).to_exprs()
