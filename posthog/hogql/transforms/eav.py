from typing import cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor


def resolve_eav_properties(node: ast.AST, context: HogQLContext) -> None:
    """
    Transform EAV property accesses into JOINs on the posthog.event_properties table.

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

        # Skip integer indices - they do positional array access on the JSON object,
        # not named property access (e.g., properties[1] returns value at position 1)
        if not isinstance(node.chain[0], str):
            return

        property_name = node.chain[0]
        prop_info = self.context.property_swapper.event_properties.get(property_name, {})
        eav_column = prop_info.get("eav")

        if eav_column is not None:
            events_alias = _get_events_table_alias(node.field_type.table_type)
            self._current_eav_properties.add((events_alias, property_name, eav_column))
            node.eav_join_alias = f"eav_{events_alias}_{property_name}"
            node.eav_column = eav_column

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
        # Sort for deterministic output
        for events_alias, property_name, _eav_column in sorted(eav_properties):
            eav_alias = f"eav_{events_alias}_{property_name}"
            join_expr = self._create_eav_join(
                eav_alias=eav_alias,
                property_name=property_name,
                events_alias=events_alias,
            )
            join_expr = cast(
                ast.JoinExpr,
                resolve_types(join_expr, self.context, dialect="clickhouse", scopes=[node.type] if node.type else None),
            )
            self._append_join(node, join_expr)

    def _create_eav_join(self, eav_alias: str, property_name: str, events_alias: str) -> ast.JoinExpr:
        """
        Create a JoinExpr for an EAV property.

        Generates:
        LEFT ANY JOIN posthog.event_properties AS {eav_alias}
            ON {events_alias}.team_id = {eav_alias}.team_id
            AND toDate({events_alias}.timestamp) = toDate({eav_alias}.timestamp)
            AND {events_alias}.event = {eav_alias}.event
            AND cityHash64({events_alias}.distinct_id) = cityHash64({eav_alias}.distinct_id)
            AND cityHash64({events_alias}.uuid) = cityHash64({eav_alias}.uuid)
            AND {eav_alias}.key = '{property_name}'
        """

        constraint_expr = ast.And(
            exprs=[
                # team_id = team_id
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[events_alias, "team_id"]),
                    right=ast.Field(chain=[eav_alias, "team_id"]),
                ),
                # toDate(timestamp) = toDate(timestamp)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="toDate", args=[ast.Field(chain=[events_alias, "timestamp"])]),
                    right=ast.Call(name="toDate", args=[ast.Field(chain=[eav_alias, "timestamp"])]),
                ),
                # event = event
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[events_alias, "event"]),
                    right=ast.Field(chain=[eav_alias, "event"]),
                ),
                # cityHash64(distinct_id) = cityHash64(distinct_id)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="cityHash64", args=[ast.Field(chain=[events_alias, "distinct_id"])]),
                    right=ast.Call(name="cityHash64", args=[ast.Field(chain=[eav_alias, "distinct_id"])]),
                ),
                # cityHash64(uuid) = cityHash64(uuid)
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="cityHash64", args=[ast.Field(chain=[events_alias, "uuid"])]),
                    right=ast.Call(name="cityHash64", args=[ast.Field(chain=[eav_alias, "uuid"])]),
                ),
                # key = property_name
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[eav_alias, "key"]),
                    right=ast.Constant(value=property_name),
                ),
            ]
        )

        return ast.JoinExpr(
            join_type="LEFT ANY JOIN",
            table=ast.Field(chain=["posthog", "event_properties"]),
            alias=eav_alias,
            constraint=ast.JoinConstraint(
                expr=constraint_expr,
                constraint_type="ON",
            ),
        )

    def _append_join(self, node: ast.SelectQuery, join_expr: ast.JoinExpr) -> None:
        """Append a JoinExpr to the end of the select_from chain."""
        assert node.select_from is not None

        current = node.select_from
        while current.next_join is not None:
            current = current.next_join

        current.next_join = join_expr
