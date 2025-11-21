from collections import defaultdict
from typing import Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    BreakdownAttributionType,
    DataWarehouseNode,
    EventsNode,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelMathType,
    StepOrderValue,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.hogql_queries.insights.funnels.funnel_aggregation_operations import FirstTimeForUserAggregationQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.utils.properties import Properties
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.property.property import PropertyName
from posthog.types import EntityNode, ExclusionEntityNode

FunnelsNode = EventsNode | ActionsNode | DataWarehouseNode


class FunnelEventQuery:
    context: FunnelQueryContext
    _entities: list[EntityNode] | None = None
    _entity_name = "events"
    _extra_event_fields_and_properties: list[ColumnName | PropertyName]

    EVENT_TABLE_ALIAS = "e"

    def __init__(
        self,
        context: FunnelQueryContext,
        entities: list[EntityNode] | None = None,
        entity_name="events",
        extra_event_fields_and_properties: Optional[list[ColumnName | PropertyName]] = None,
    ):
        if extra_event_fields_and_properties is None:
            extra_event_fields_and_properties = []

        self.context = context
        self._entities = entities
        self._entity_name = entity_name
        self._extra_event_fields_and_properties = extra_event_fields_and_properties

    @property
    def extra_fields(self):
        extra_fields_from_context: list[str] = []

        for prop in self.context.includeProperties:
            extra_fields_from_context.append(prop)

        return [*self._extra_event_fields_and_properties, *extra_fields_from_context]

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
            funnelsFilter = self.context.funnelsFilter
            entities_to_use = self._entities or self.context.query.series

            all_step_cols: list[ast.Expr] = []
            all_exclusions: list[list[FunnelExclusionEventsNode | FunnelExclusionActionsNode]] = []
            for index, entity in enumerate(entities_to_use):
                step_cols = self._get_step_col(entity, index, self._entity_name, for_udf=True)
                all_step_cols.extend(step_cols)
                all_exclusions.append([])

            if funnelsFilter.exclusions:
                for excluded_entity in funnelsFilter.exclusions:
                    for i in range(excluded_entity.funnelFromStep + 1, excluded_entity.funnelToStep + 1):
                        all_exclusions[i].append(excluded_entity)

                for index, exclusions in enumerate(all_exclusions):
                    exclusion_col_expr = self._get_exclusions_col(exclusions, index, self._entity_name)
                    all_step_cols.append(exclusion_col_expr)

            breakdown_select_prop = self._get_breakdown_select_prop(for_udf=True)

            if breakdown_select_prop:
                all_step_cols.extend(breakdown_select_prop)

            _extra_fields: list[ast.Expr] = [
                ast.Alias(alias=field, expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, field]))
                for field in self.extra_fields
            ]

            select: list[ast.Expr] = [
                ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
                ast.Alias(alias="aggregation_target", expr=self._aggregation_target_expr()),
                *_extra_fields,
                *all_step_cols,
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
            # TODO: Add step columns and step where conditions here
            table_alias = self.EVENT_TABLE_ALIAS
            node = steps[0][1]

            _extra_fields: list[ast.Expr] = [
                ast.Alias(alias=field, expr=ast.Constant(value=None)) for field in self.extra_fields
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

        for field in self.extra_fields:
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

    def _get_exclusions_col(
        self,
        exclusions: list[ExclusionEntityNode],
        index: int,
        entity_name: str,
    ) -> ast.Expr:
        if not exclusions:
            return parse_expr(f"0 as exclusion_{index}")
        conditions = [self._build_step_query(exclusion, index, entity_name, "") for exclusion in exclusions]
        return parse_expr(
            f"if({{condition}}, 1, 0) as exclusion_{index}", placeholders={"condition": ast.Or(exprs=conditions)}
        )

    def _get_step_col(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str = "",
        for_udf: bool = False,
    ) -> list[ast.Expr]:
        # step prefix is used to distinguish actual steps, and exclusion steps
        # without the prefix, we get the same parameter binding for both, which borks things up
        step_cols: list[ast.Expr] = []
        condition = self._build_step_query(entity, index, entity_name, step_prefix)
        step_cols.append(
            parse_expr(f"if({{condition}}, 1, 0) as {step_prefix}step_{index}", placeholders={"condition": condition})
        )
        if not for_udf:
            step_cols.append(
                parse_expr(f"if({step_prefix}step_{index} = 1, timestamp, null) as {step_prefix}latest_{index}")
            )

            for field in self._extra_event_fields_and_properties:
                step_cols.append(
                    parse_expr(f'if({step_prefix}step_{index} = 1, "{field}", null) as "{step_prefix}{field}_{index}"')
                )

        return step_cols

    def _build_step_query(
        self,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
        entity_name: str,
        step_prefix: str,
    ) -> ast.Expr:
        filters: list[ast.Expr] = []

        if isinstance(entity, ActionsNode) or isinstance(entity, FunnelExclusionActionsNode):
            # action
            action = Action.objects.get(pk=int(entity.id), team__project_id=self.context.team.project_id)
            event_expr = action_to_expr(action)
        elif isinstance(entity, DataWarehouseNode):
            event_expr = ast.Constant(value=1)
            # raise ValidationError(
            #     "Data warehouse tables are not supported in funnels just yet. For now, please try this funnel without the data warehouse-based step."
            # )
        elif entity.event is None:
            # all events
            event_expr = ast.Constant(value=1)
        else:
            # event
            event_expr = parse_expr("event = {event}", {"event": ast.Constant(value=entity.event)})

        filters.append(event_expr)

        filter_expr: ast.Expr | None = None
        if entity.properties is not None and entity.properties != []:
            # add property filters
            filter_expr = property_to_expr(entity.properties, self.context.team)
            filters.append(filter_expr)

        if entity.math == FunnelMathType.FIRST_TIME_FOR_USER:
            subquery = FirstTimeForUserAggregationQuery(self.context, filter_expr, event_expr).to_query()
            first_time_filter = ast.CompareOperation(
                left=ast.Field(chain=["e", "uuid"]), right=subquery, op=ast.CompareOperationOp.GlobalIn
            )
            return ast.And(exprs=[*filters, first_time_filter])
        elif entity.math == FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS:
            subquery = FirstTimeForUserAggregationQuery(
                self.context, ast.Constant(value=1), ast.And(exprs=filters)
            ).to_query()
            first_time_filter = ast.CompareOperation(
                left=ast.Field(chain=["e", "uuid"]), right=subquery, op=ast.CompareOperationOp.GlobalIn
            )
            return ast.And(exprs=[*filters, first_time_filter])
        elif len(filters) > 1:
            return ast.And(exprs=filters)
        return filters[0]

    def _get_breakdown_select_prop(self, for_udf=False) -> list[ast.Expr]:
        breakdown, breakdownAttributionType, funnelsFilter = (
            self.context.breakdown,
            self.context.breakdownAttributionType,
            self.context.funnelsFilter,
        )

        if not breakdown:
            return []

        # breakdown prop
        prop_basic = ast.Alias(alias="prop_basic", expr=self._get_breakdown_expr())

        # breakdown attribution
        if breakdownAttributionType == BreakdownAttributionType.STEP:
            select_columns = []
            default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "NULL"

            # Unordered funnels can have any step be the Nth step
            if for_udf and funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
                final_select = parse_expr(f"prop_basic as prop")
            else:
                # get prop value from each step
                for index, _ in enumerate(self.context.query.series):
                    select_columns.append(
                        parse_expr(f"if(step_{index} = 1, prop_basic, {default_breakdown_selector}) as prop_{index}")
                    )

                final_select = parse_expr(f"prop_{funnelsFilter.breakdownAttributionValue} as prop")

            if for_udf:
                return [prop_basic, *select_columns, final_select]

            prop_window = parse_expr("groupUniqArray(prop) over (PARTITION by aggregation_target) as prop_vals")
            return [prop_basic, *select_columns, final_select, prop_window]
        elif breakdownAttributionType in [
            BreakdownAttributionType.FIRST_TOUCH,
            BreakdownAttributionType.LAST_TOUCH,
        ]:
            prop_conditional = (
                "notEmpty(arrayFilter(x -> notEmpty(x), prop))"
                if self._query_has_array_breakdown()
                else "isNotNull(prop)"
            )

            aggregate_operation = (
                "argMinIf" if breakdownAttributionType == BreakdownAttributionType.FIRST_TOUCH else "argMaxIf"
            )

            breakdown_window_selector = f"{aggregate_operation}(prop, timestamp, {prop_conditional})"
            if for_udf:
                return [prop_basic, ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"]))]
            prop_window = parse_expr(f"{breakdown_window_selector} over (PARTITION by aggregation_target) as prop_vals")
            return [
                prop_basic,
                ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"])),
                prop_window,
            ]
        else:
            # all_events
            return [
                prop_basic,
                ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"])),
            ]

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
