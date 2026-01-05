from collections import defaultdict
from collections.abc import Sequence
from typing import Optional, Union, cast

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
from posthog.hogql.database.models import DateTimeDatabaseField, StringDatabaseField
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.hogql_queries.insights.funnels.funnel_aggregation_operations import FirstTimeForUserAggregationQuery
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import (
    SourceTableKind,
    alias_columns_in_select,
    entity_source_mismatch,
    entity_source_or_table_mismatch,
    get_breakdown_expr,
    get_table_name,
    is_data_warehouse_source,
)
from posthog.hogql_queries.insights.utils.data_warehouse_schema_mixin import DataWarehouseSchemaMixin
from posthog.hogql_queries.insights.utils.properties import Properties
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.property.property import PropertyName
from posthog.types import EntityNode, ExclusionEntityNode


class FunnelEventQuery(DataWarehouseSchemaMixin):
    context: FunnelQueryContext
    _extra_event_fields_and_properties: list[ColumnName | PropertyName]

    EVENT_TABLE_ALIAS = "e"

    def __init__(
        self,
        context: FunnelQueryContext,
        extra_event_fields_and_properties: Optional[list[ColumnName | PropertyName]] = None,
    ):
        if extra_event_fields_and_properties is None:
            extra_event_fields_and_properties = []

        self.context = context
        self._extra_event_fields_and_properties = extra_event_fields_and_properties

    @property
    def extra_fields(self):
        extra_fields_from_context: list[str] = []

        for prop in self.context.includeProperties:
            extra_fields_from_context.append(prop)

        return [*self._extra_event_fields_and_properties, *extra_fields_from_context]

    @property
    def exclusions_by_index(self):
        series, funnelsFilter = self.context.query.series, self.context.funnelsFilter

        result: list[list[ExclusionEntityNode]] = [[] for _ in series]
        exclusions = funnelsFilter.exclusions or []

        for exclusion in exclusions:
            for i in range(exclusion.funnelFromStep + 1, exclusion.funnelToStep + 1):
                result[i].append(exclusion)

        return result

    def to_query(self, skip_entity_filter=False, skip_step_filter=False) -> ast.SelectQuery:
        tables_to_steps: dict[str, list[tuple[int, EntityNode]]] = defaultdict(list)

        for step_index, node in enumerate(self.context.query.series):
            table_name = get_table_name(node)
            tables_to_steps[table_name].append((step_index, node))

        def _build_events_table_query(
            table_name: str, steps: Sequence[tuple[int, EventsNode | ActionsNode]]
        ) -> ast.SelectQuery:
            all_step_cols = self._get_funnel_cols(SourceTableKind.EVENTS, table_name)

            select: list[ast.Expr] = [
                ast.Alias(alias="timestamp", expr=ast.Field(chain=[self.EVENT_TABLE_ALIAS, "timestamp"])),
                ast.Alias(alias="aggregation_target", expr=self._aggregation_target_expr()),
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

            if not skip_step_filter:
                steps_conditions = self._get_steps_conditions(SourceTableKind.EVENTS, steps)
                where = ast.And(exprs=[where, steps_conditions])

            stmt = ast.SelectQuery(
                select=select,
                select_from=select_from,
                where=where,
            )
            return stmt

        def _build_data_warehouse_table_query(
            table_name: str, steps: Sequence[tuple[int, DataWarehouseNode]]
        ) -> ast.SelectQuery:
            node = steps[0][1]

            all_step_cols = self._get_funnel_cols(SourceTableKind.DATA_WAREHOUSE, table_name, node)

            field = self.get_warehouse_field(node.table_name, node.timestamp_field)

            timestamp_expr: ast.Expr
            # TODO: Move validations to funnel base / series entity
            if isinstance(field, DateTimeDatabaseField):
                timestamp_expr = ast.Field(chain=[self.EVENT_TABLE_ALIAS, node.timestamp_field])
            elif isinstance(field, StringDatabaseField):
                timestamp_expr = ast.Call(
                    name="toDateTime", args=[ast.Field(chain=[self.EVENT_TABLE_ALIAS, node.timestamp_field])]
                )
            else:
                raise ValidationError(
                    detail=f"Unsupported timestamp field type for {node.table_name}.{node.timestamp_field}"
                )

            select: list[ast.Expr] = [
                ast.Alias(
                    alias="timestamp",
                    expr=timestamp_expr,
                ),
                ast.Alias(
                    alias="aggregation_target",
                    expr=ast.Call(
                        name="toUUID", args=[ast.Field(chain=[self.EVENT_TABLE_ALIAS, node.distinct_id_field])]
                    ),
                ),
                *all_step_cols,
            ]

            select_from = ast.JoinExpr(table=ast.Field(chain=[table_name]), alias=self.EVENT_TABLE_ALIAS)

            date_range = self._date_range()
            where_exprs: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=date_range.date_from()),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=date_range.date_to()),
                ),
            ]
            where = ast.And(exprs=[expr for expr in where_exprs if expr is not None])

            if not skip_step_filter:
                steps_conditions = self._get_steps_conditions(SourceTableKind.DATA_WAREHOUSE, steps)
                where = ast.And(exprs=[where, steps_conditions])

            return ast.SelectQuery(
                select=select,
                select_from=select_from,
                where=where,
            )

        queries: list[ast.SelectQuery] = []

        for table_name, steps in tables_to_steps.items():
            if table_name == "events":
                event_steps = cast(Sequence[tuple[int, EventsNode | ActionsNode]], steps)
                queries.append(_build_events_table_query(table_name, event_steps))
            else:
                dwh_steps = cast(Sequence[tuple[int, DataWarehouseNode]], steps)
                queries.append(_build_data_warehouse_table_query(table_name, dwh_steps))

        if len(queries) == 1:
            return queries[0]

        # Take the field and alias names from the first query. UNION enforces identical column sets
        # across all selects, which makes this reliable.
        aliased_fields = alias_columns_in_select(queries[0].select, self.EVENT_TABLE_ALIAS)

        return ast.SelectQuery(
            select=aliased_fields,
            select_from=ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries(queries, "UNION ALL"),
                alias=self.EVENT_TABLE_ALIAS,
            ),
        )

    def _get_funnel_cols(
        self, source_kind: SourceTableKind, table_name: str, node: Optional[DataWarehouseNode] = None
    ) -> list[ast.Expr]:
        cols: list[ast.Expr] = []

        # extra fields
        cols.extend(self._get_extra_fields(source_kind, node))

        # step cols
        for index, entity in enumerate(self.context.query.series):
            step_col = self._get_step_col(source_kind, table_name, entity, index)
            cols.append(step_col)

        # exclusion cols
        if self.context.funnelsFilter.exclusions:
            for index, exclusions in enumerate(self.exclusions_by_index):
                exclusion_col_expr = self._get_exclusions_col(source_kind, table_name, exclusions, index)
                cols.append(exclusion_col_expr)

        # breakdown (attribution) col
        cols.extend(self._get_breakdown_select_prop(source_kind))

        return cols

    def _get_step_col(
        self,
        source_kind: SourceTableKind,
        table_name: str,
        entity: EntityNode,
        index: int,
    ) -> ast.Expr:
        if entity_source_or_table_mismatch(entity, source_kind, table_name):
            return parse_expr(f"0 as step_{index}")

        condition = self._build_step_query(source_kind, table_name, entity, index)
        return parse_expr(f"if({{condition}}, 1, 0) as step_{index}", placeholders={"condition": condition})

    def _get_exclusions_col(
        self,
        source_kind: SourceTableKind,
        table_name: str,
        exclusions: list[ExclusionEntityNode],
        index: int,
    ) -> ast.Expr:
        if is_data_warehouse_source(source_kind) or len(exclusions) == 0:
            return parse_expr(f"0 as exclusion_{index}")
        conditions = [self._build_step_query(source_kind, table_name, exclusion, index) for exclusion in exclusions]
        return parse_expr(
            f"if({{condition}}, 1, 0) as exclusion_{index}", placeholders={"condition": ast.Or(exprs=conditions)}
        )

    def _build_step_query(
        self,
        source_kind: SourceTableKind,
        table_name: str,
        entity: EntityNode | ExclusionEntityNode,
        index: int,
    ) -> ast.Expr:
        filters: list[ast.Expr] = []

        if isinstance(entity, ActionsNode) or isinstance(entity, FunnelExclusionActionsNode):
            # action
            try:
                action = Action.objects.get(pk=int(entity.id), team__project_id=self.context.team.project_id)
            except Action.DoesNotExist:
                raise ValidationError(f"Action ID {entity.id} does not exist!")
            event_expr = action_to_expr(action)
        elif isinstance(entity, DataWarehouseNode):
            if is_data_warehouse_source(source_kind) and table_name == entity.table_name:
                event_expr = ast.Constant(value=1)
            else:
                event_expr = ast.Constant(value=0)
        elif entity.event is None:
            # all events
            if is_data_warehouse_source(source_kind):
                event_expr = ast.Constant(value=0)
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

    def _get_steps_conditions(self, source_kind: SourceTableKind, steps: Sequence[tuple[int, EntityNode]]) -> ast.Expr:
        step_conditions: list[ast.Expr] = []

        for index, step in steps:
            if not entity_source_mismatch(step, source_kind):
                step_conditions.append(parse_expr(f"step_{index} = 1"))
                if self.exclusions_by_index[index]:
                    step_conditions.append(parse_expr(f"exclusion_{index} = 1"))

        return ast.Or(exprs=step_conditions)

    def _get_breakdown_expr(self) -> ast.Expr:
        breakdown, breakdownType, breakdownFilter = (
            self.context.breakdown,
            self.context.breakdownType,
            self.context.breakdownFilter,
        )

        assert breakdown is not None

        if breakdownType == "person":
            properties_column = "person.properties"
            return get_breakdown_expr(breakdown, properties_column)
        elif breakdownType == "event":
            properties_column = "properties"
            normalize_url = breakdownFilter.breakdown_normalize_url
            return get_breakdown_expr(breakdown, properties_column, normalize_url=normalize_url)
        elif breakdownType == "cohort":
            return ast.Field(chain=["value"])
        elif breakdownType == "group":
            properties_column = f"group_{breakdownFilter.breakdown_group_type_index}.properties"
            return get_breakdown_expr(breakdown, properties_column)
        elif breakdownType == "hogql" or breakdownType == "event_metadata":
            assert isinstance(breakdown, list)
            return ast.Alias(
                alias="value",
                expr=ast.Array(exprs=[parse_expr(str(value)) for value in breakdown]),
            )
        elif breakdownType == "data_warehouse_person_property" and isinstance(breakdown, str):
            return ast.Field(chain=["person", *breakdown.split(".")])
        else:
            raise ValidationError(detail=f"Unsupported breakdown type: {breakdownType}")

    def _query_has_array_breakdown(self) -> bool:
        breakdown, breakdownType = self.context.breakdown, self.context.breakdownType
        return breakdown is not None and not isinstance(breakdown, str) and breakdownType != "cohort"

    def _get_breakdown_select_prop(self, source_kind: SourceTableKind) -> list[ast.Expr]:
        default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "NULL"

        breakdown, breakdownAttributionType, funnelsFilter = (
            self.context.breakdown,
            self.context.breakdownAttributionType,
            self.context.funnelsFilter,
        )

        if not breakdown:
            return []

        # breakdown prop
        prop_basic: ast.Expr
        if source_kind == SourceTableKind.EVENTS:
            prop_basic = ast.Alias(alias="prop_basic", expr=self._get_breakdown_expr())
        else:
            prop_basic = parse_expr(f"{default_breakdown_selector} as prop_basic")

        # breakdown attribution
        if (
            breakdownAttributionType == BreakdownAttributionType.STEP
            and funnelsFilter.funnelOrderType != StepOrderValue.UNORDERED
        ):
            prop = parse_expr(
                f"if(step_{funnelsFilter.breakdownAttributionValue} = 1, prop_basic, {default_breakdown_selector}) as prop"
            )
            return [prop_basic, prop]
        elif (
            breakdownAttributionType
            in [
                BreakdownAttributionType.FIRST_TOUCH,
                BreakdownAttributionType.LAST_TOUCH,
                BreakdownAttributionType.ALL_EVENTS,
            ]
            # Unordered funnels can have any step be the Nth step
            or breakdownAttributionType == BreakdownAttributionType.STEP
            and funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED
        ):
            return [prop_basic, ast.Alias(alias="prop", expr=ast.Field(chain=["prop_basic"]))]
        else:
            raise ValidationError(f"Unknown breakdown attribution type {breakdownAttributionType}")

    def _get_extra_fields(
        self, source_kind: SourceTableKind, node: Optional[DataWarehouseNode] = None
    ) -> list[ast.Expr]:
        def _expr_for(field: str) -> ast.Expr:
            if is_data_warehouse_source(source_kind):
                assert isinstance(node, DataWarehouseNode)
                if field == "uuid":
                    return ast.Alias(
                        alias="uuid",
                        expr=ast.Call(name="toUUID", args=[ast.Field(chain=[self.EVENT_TABLE_ALIAS, node.id_field])]),
                    )
                return ast.Constant(value=None)
            return ast.Field(chain=[self.EVENT_TABLE_ALIAS, field])

        return [ast.Alias(alias=field, expr=_expr_for(field)) for field in self.extra_fields]

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
