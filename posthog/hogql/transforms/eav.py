from typing import cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor


def resolve_eav_properties(node: ast.AST, context: HogQLContext) -> None:
    """
    Transform EAV property accesses into JOINs on the event_properties table.

    This mutates the AST in place:
    1. For each SelectQuery, finds PropertyType nodes that need EAV
    2. Adds JoinExpr nodes to select_from for each EAV property
    3. Sets eav_join_alias and eav_column on PropertyType so the printer outputs alias.column
    """
    EAVResolver(context=context).visit(node)


def _get_events_table_alias(table_type: ast.BaseTableType) -> str:
    """Get the alias for an events table (either explicit alias or 'events')."""
    if isinstance(table_type, ast.TableAliasType):
        return table_type.alias
    return "events"


class EAVResolver(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        # EAV properties for the current SELECT scope
        # Each entry: (events_alias, property_name, eav_column)
        self._current_eav_properties: set[tuple[str, str, str]] = set()

    def visit_property_type(self, node: ast.PropertyType):
        if not self.context.property_swapper:
            return

        if node.field_type.name != "properties" or len(node.chain) != 1:
            return

        if not isinstance(node.field_type.table_type, ast.BaseTableType):
            return

        resolved_table = node.field_type.table_type.resolve_database_table(self.context)
        if not isinstance(resolved_table, EventsTable):
            return

        property_name = str(node.chain[0])
        prop_info = self.context.property_swapper.event_properties.get(property_name, {})
        eav_column = prop_info.get("eav")

        if eav_column is not None:
            events_alias = _get_events_table_alias(node.field_type.table_type)
            self._current_eav_properties.add((events_alias, property_name, eav_column))

    def visit_select_query(self, node: ast.SelectQuery):
        # Save current set and create new one for this SELECT's scope
        old_eav_properties = self._current_eav_properties
        self._current_eav_properties = set()

        # Visit all child nodes to collect EAV property accesses
        super().visit_select_query(node)

        # Get the EAV properties for this SELECT and restore parent scope
        eav_properties = self._current_eav_properties
        self._current_eav_properties = old_eav_properties

        if not eav_properties:
            return

        # Create JoinExpr nodes and add them to the select_from chain
        for events_alias, property_name, _eav_column in eav_properties:
            eav_alias = f"eav_{events_alias}_{property_name}"
            join_expr = self._create_eav_join(
                eav_alias=eav_alias,
                property_name=property_name,
                events_alias=events_alias,
            )
            # Resolve types on the new JoinExpr so the printer can handle it
            join_expr = cast(
                ast.JoinExpr,
                resolve_types(join_expr, self.context, dialect="clickhouse", scopes=[node.type] if node.type else None),
            )
            self._append_join(node, join_expr)

        # Now update PropertyType nodes to reference the EAV aliases
        PropertyTypeUpdater(
            context=self.context,
            eav_properties=eav_properties,
        ).visit(node)

    def _create_eav_join(self, eav_alias: str, property_name: str, events_alias: str) -> ast.JoinExpr:
        """
        Create a JoinExpr for an EAV property.

        Generates:
        ANY LEFT JOIN event_properties AS {eav_alias}
            ON {events_alias}.team_id = {eav_alias}.team_id
            AND toDate({events_alias}.timestamp) = toDate({eav_alias}.timestamp)
            AND {events_alias}.event = {eav_alias}.event
            AND cityHash64({events_alias}.distinct_id) = cityHash64({eav_alias}.distinct_id)
            AND cityHash64({events_alias}.uuid) = cityHash64({eav_alias}.uuid)
            AND {eav_alias}.key = '{property_name}'
        """
        e = events_alias
        a = eav_alias

        constraint_expr = ast.And(
            exprs=[
                # team_id = team_id
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[e, "team_id"]),
                    right=ast.Field(chain=[a, "team_id"]),
                ),
                # toDate(timestamp) = toDate(timestamp)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="toDate", args=[ast.Field(chain=[e, "timestamp"])]),
                    right=ast.Call(name="toDate", args=[ast.Field(chain=[a, "timestamp"])]),
                ),
                # event = event
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[e, "event"]),
                    right=ast.Field(chain=[a, "event"]),
                ),
                # cityHash64(distinct_id) = cityHash64(distinct_id)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="cityHash64", args=[ast.Field(chain=[e, "distinct_id"])]),
                    right=ast.Call(name="cityHash64", args=[ast.Field(chain=[a, "distinct_id"])]),
                ),
                # cityHash64(uuid) = cityHash64(uuid)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="cityHash64", args=[ast.Field(chain=[e, "uuid"])]),
                    right=ast.Call(name="cityHash64", args=[ast.Field(chain=[a, "uuid"])]),
                ),
                # key = property_name
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[a, "key"]),
                    right=ast.Constant(value=property_name),
                ),
            ]
        )

        return ast.JoinExpr(
            join_type="LEFT ANY JOIN",
            table=ast.Field(chain=["event_properties"]),
            alias=eav_alias,
            constraint=ast.JoinConstraint(
                expr=constraint_expr,
                constraint_type="ON",
            ),
        )

    def _append_join(self, node: ast.SelectQuery, join_expr: ast.JoinExpr) -> None:
        """Append a JoinExpr to the end of the select_from chain."""
        if node.select_from is None:
            node.select_from = join_expr
            return

        # Walk to the end of the join chain
        current = node.select_from
        while current.next_join is not None:
            current = current.next_join

        current.next_join = join_expr


class PropertyTypeUpdater(TraversingVisitor):
    """
    Update PropertyType nodes to reference EAV aliases.

    After EAV JOINs are added, this updates the PropertyType nodes
    to set eav_join_alias and eav_column so the printer outputs alias.column.
    """

    def __init__(self, context: HogQLContext, eav_properties: set[tuple[str, str, str]]):
        super().__init__()
        self.context = context
        # Map (events_alias, property_name) -> (eav_alias, eav_column)
        self.eav_map: dict[tuple[str, str], tuple[str, str]] = {}
        for events_alias, property_name, eav_column in eav_properties:
            eav_alias = f"eav_{events_alias}_{property_name}"
            self.eav_map[(events_alias, property_name)] = (eav_alias, eav_column)
        self._in_target_select = False

    def visit_select_query(self, node: ast.SelectQuery):
        if self._in_target_select:
            # Don't descend into nested subqueries - they have their own EAV joins
            pass
        else:
            # Visit the target SELECT's expressions
            self._in_target_select = True
            super().visit_select_query(node)
            self._in_target_select = False

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        # Don't descend into union queries
        pass

    def visit_property_type(self, node: ast.PropertyType):
        if node.field_type.name != "properties" or len(node.chain) != 1:
            return

        if not isinstance(node.field_type.table_type, ast.BaseTableType):
            return

        resolved_table = node.field_type.table_type.resolve_database_table(self.context)
        if not isinstance(resolved_table, EventsTable):
            return

        property_name = str(node.chain[0])
        events_alias = _get_events_table_alias(node.field_type.table_type)

        if (events_alias, property_name) in self.eav_map:
            eav_alias, eav_column = self.eav_map[(events_alias, property_name)]
            node.eav_join_alias = eav_alias
            node.eav_column = eav_column
