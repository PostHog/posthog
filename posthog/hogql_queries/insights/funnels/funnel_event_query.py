from typing import List, Optional
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.models.team.team import Team
from posthog.schema import FunnelsQuery, HogQLQueryModifiers


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
        # entities=None,
        # entity_name="events",
        # skip_entity_filter=False,
    ) -> ast.SelectQuery:
        select: List[ast.Expr] = [
            ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
            ast.Alias(alias="aggregation_target", expr=ast.Field(chain=[self.aggregation_target_column()])),
        ]

        select_from = ast.JoinExpr(
            table=ast.Field(chain=["events"]),
            alias=self.EVENT_TABLE_ALIAS,
            sample=self.sample_expr(),
        )

        where_exprs = [self.date_range_expr()]

        # prop_query = self._get_prop_groups(
        #     self._filter.property_groups,
        #     person_properties_mode=get_person_properties_mode(self._team),
        #     person_id_joined_alias=self._person_id_alias,
        # )

        # if not skip_entity_filter:
        #     entity_query = self._get_entity_query(entities, entity_name)

        # person_query = self._get_person_query()

        # query = f"""
        #     {self._get_person_ids_query()}
        #     {person_query}
        #     WHERE
        #     {entity_query}
        #     {prop_query}
        # """
        where = ast.And(exprs=where_exprs)

        # return query, self.params
        stmt = ast.SelectQuery(
            select=select,
            select_from=select_from,
            where=where,
        )
        return stmt

    def aggregation_target_column(self) -> str:
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

    def sample_expr(self) -> ast.SampleExpr | None:
        if self.query.samplingFactor is None:
            return None
        else:
            return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor)))

    def date_range_expr(self) -> ast.Expr:
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

    # def _get_entity_query(self, entities=None, entity_name="events") -> Tuple[str, Dict[str, Any]]:
    #     events: Set[Union[int, str, None]] = set()
    #     entities_to_use = entities or self._filter.entities

    #     for entity in entities_to_use:
    #         if entity.type == TREND_FILTER_TYPE_ACTIONS:
    #             action = entity.get_action()
    #             events.update(action.get_step_events())
    #         else:
    #             events.add(entity.id)

    #     # If selecting for "All events", disable entity pre-filtering
    #     if None in events:
    #         return "AND 1 = 1", {}

    #     return f"AND event IN %({entity_name})s", {entity_name: sorted(list(events))}
