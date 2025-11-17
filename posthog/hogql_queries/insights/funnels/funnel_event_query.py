from collections import defaultdict
from typing import Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.properties import Properties
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.property.property import PropertyName


FunnelsNode = EventsNode | ActionsNode | DataWarehouseNode


class FunnelEventQuery:
    context: FunnelQueryContext
    _extra_fields: list[ColumnName]
    _extra_event_properties: list[PropertyName]

    EVENT_TABLE_ALIAS = "e"

    def __init__(
        self,
        context: FunnelQueryContext,
        extra_fields: Optional[list[ColumnName]] = None,
        extra_event_properties: Optional[list[PropertyName]] = None,
    ):
        if extra_event_properties is None:
            extra_event_properties = []
        if extra_fields is None:
            extra_fields = []
        self.context = context

        self._extra_fields = extra_fields
        self._extra_event_properties = extra_event_properties

    def to_query(
        self,
        skip_entity_filter=False,
    ) -> ast.SelectQuery:
        def _get_table_name(node: FunnelsNode):
            if isinstance(node, DataWarehouseNode):
                return node.table_name
            else:
                return "events"

        tables_to_steps: dict[str, list[tuple[int, FunnelsNode]]] = defaultdict(list)

        for step_index, node in enumerate(self.context.query.series):
            table_name = _get_table_name(node)
            tables_to_steps[table_name].append((step_index, node))

        def _build_events_table_query(steps: list[tuple[int, EventsNode | ActionsNode]]) -> ast.SelectQuery:
            _extra_fields: list[ast.Expr] = [
                ast.Alias(alias=field, expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, field]))
                for field in self._extra_fields
            ]

            select: list[ast.Expr] = [
                ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
                ast.Alias(alias="aggregation_target", expr=self._aggregation_target_expr()),
                *_extra_fields,
            ]

            select_from = ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                alias=self.EVENT_TABLE_ALIAS,
                sample=self._sample_expr(),
            )

            where_exprs = [
                self._date_range_expr(),
                self._entity_expr(skip_entity_filter),
                *self._properties_expr(),
                self._aggregation_target_filter(),
            ]
            where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

            stmt = ast.SelectQuery(
                select=select,
                select_from=select_from,
                where=where,
            )
            return stmt

        def _build_data_warehouse_table_query(
            table_name: str, steps: list[tuple[int, DataWarehouseNode]]
        ) -> ast.SelectQuery:
            table_alias = self.EVENT_TABLE_ALIAS
            node = steps[0][1]

            _extra_fields: list[ast.Expr] = [
                ast.Alias(alias=field, expr=ast.Constant(value=None)) for field in self._extra_fields
            ]

            select: list[ast.Expr] = [
                ast.Alias(alias="timestamp", expr=ast.Field(chain=[table_alias, node.timestamp_field])),
                ast.Alias(alias="aggregation_target", expr=ast.Field(chain=[table_alias, node.distinct_id_field])),
                *_extra_fields,
            ]

            date_range = self._date_range()
            where_exprs: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=[table_alias, node.timestamp_field]),
                    right=ast.Constant(value=date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=[table_alias, node.timestamp_field]),
                    right=ast.Constant(value=date_range.date_to()),
                ),
            ]

            aggregation_target_filter = self._aggregation_target_filter()
            if aggregation_target_filter is not None:
                where_exprs.append(aggregation_target_filter)

            where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

            return ast.SelectQuery(
                select=select,
                select_from=ast.JoinExpr(table=ast.Field(chain=[table_name]), alias=table_alias),
                where=where,
            )

        queries: list[ast.SelectQuery] = []

        for table_name, steps in tables_to_steps.items():
            if table_name == "events":
                queries.append(_build_events_table_query(steps))
            else:
                queries.append(_build_data_warehouse_table_query(table_name, steps))

        if len(queries) == 1:
            return queries[0]

        union_selects: list[ast.Expr] = [
            ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
            ast.Alias(alias="aggregation_target", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "aggregation_target"])),
        ]

        for field in self._extra_fields:
            union_selects.append(
                ast.Alias(alias=field, expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, field])),
            )

        return ast.SelectQuery(
            select=union_selects,
            select_from=ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries(queries, "UNION ALL"),
                alias=self.EVENT_TABLE_ALIAS,
            ),
        )

    def _aggregation_target_expr(self) -> ast.Expr:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter

        # Aggregating by Person ID
        aggregation_target: str | ast.Expr = "person_id"

        # Aggregating by group
        if query.aggregation_group_type_index is not None:
            aggregation_target = f"$group_{query.aggregation_group_type_index}"

        # Aggregating by HogQL
        elif funnelsFilter.funnelAggregateByHogQL and funnelsFilter.funnelAggregateByHogQL != "person_id":
            aggregation_target = parse_expr(funnelsFilter.funnelAggregateByHogQL)

        if isinstance(aggregation_target, str):
            return ast.Field(chain=[aggregation_target])
        else:
            return aggregation_target

    def _aggregation_target_filter(self) -> ast.Expr | None:
        if self._aggregation_target_expr() == ast.Field(chain=["person_id"]):
            return None

        return parse_expr("aggregation_target != '' and aggregation_target != null")

    def _sample_expr(self) -> ast.SampleExpr | None:
        query = self.context.query

        if query.samplingFactor is None:
            return None
        else:
            return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=query.samplingFactor)))

    def _date_range(self) -> QueryDateRange:
        team, query, now = self.context.team, self.context.query, self.context.now

        date_range = QueryDateRange(
            date_range=query.dateRange,
            team=team,
            interval=query.interval,
            now=now,
        )

        return date_range

    def _date_range_expr(self) -> ast.Expr:
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"]),
                    right=ast.Constant(value=self._date_range().date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"]),
                    right=ast.Constant(value=self._date_range().date_to()),
                ),
            ]
        )

    def _entity_expr(self, skip_entity_filter: bool) -> ast.Expr | None:
        query, funnelsFilter = self.context.query, self.context.funnelsFilter
        exclusions = funnelsFilter.exclusions or []

        if skip_entity_filter is True:
            return None

        events: set[Union[int, str, None]] = set()

        for node in [*query.series, *exclusions]:
            if isinstance(node, EventsNode) or isinstance(node, FunnelExclusionEventsNode):
                events.add(node.event)
            elif isinstance(node, ActionsNode) or isinstance(node, FunnelExclusionActionsNode):
                try:
                    action = Action.objects.get(pk=int(node.id), team__project_id=self.context.team.project_id)
                    events.update(action.get_step_events())
                except Action.DoesNotExist:
                    raise ValidationError(f"Action ID {node.id} does not exist!")
            elif isinstance(node, DataWarehouseNode):
                continue  # Data warehouse nodes aren't based on events
            else:
                raise ValidationError("Series and exclusions must be compose of action and event nodes")

        # Disable entity pre-filtering for "All events"
        if None in events:
            return None

        return ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            # Sorting for consistent snapshots in tests
            right=ast.Tuple(exprs=[ast.Constant(value=event) for event in sorted(events)]),  # type: ignore
            op=ast.CompareOperationOp.In,
        )

    def _properties_expr(self) -> list[ast.Expr]:
        return Properties(context=self.context).to_exprs()
