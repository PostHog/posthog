"""
EAV (Entity-Attribute-Value) join transform for event properties.

This module provides functions for handling EAV-materialized properties in HogQL.
It finds EAV properties in queries and stores JOIN info in context for the printer.
"""

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor


class EAVPropertyFinder(TraversingVisitor):
    """Find all event properties that should use EAV joins."""

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.eav_properties: dict[str, str] = {}  # property_name -> value_column

    def visit_property_type(self, node: ast.PropertyType):
        if not self.context.property_swapper:
            return

        if node.field_type.name != "properties" or len(node.chain) != 1:
            return

        if not isinstance(node.field_type.table_type, ast.BaseTableType):
            return

        table_type = node.field_type.table_type
        table_name = table_type.resolve_database_table(self.context).to_printed_hogql()

        if table_name != "events":
            return

        property_name = str(node.chain[0])
        prop_info = self.context.property_swapper.event_properties.get(property_name, {})

        eav_column = prop_info.get("eav")
        if eav_column is not None:
            self.eav_properties[property_name] = eav_column


def add_eav_joins(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """
    Process a SelectQuery for EAV materialized event properties.

    This function:
    1. Finds all event properties that have EAV materialization enabled
    2. Stores EAV JOIN info in the context for the printer to use

    The printer will:
    - Generate JOIN SQL from context.eav_joins
    - Output eav_alias.value_column for EAV properties (computed from property name)
    """
    if not context.property_swapper:
        return node

    # Find all EAV properties in the query
    finder = EAVPropertyFinder(context)
    finder.visit(node)

    if not finder.eav_properties:
        return node

    # Get the events table alias (usually "events" or "e")
    events_alias = _get_events_alias(node)
    if not events_alias:
        return node

    # Store EAV join info in context for the printer to use
    # The printer will generate the actual JOIN SQL and output column references
    if not hasattr(context, "eav_joins"):
        context.eav_joins = {}  # type: ignore[attr-defined]

    for property_name, value_column in finder.eav_properties.items():
        alias = f"eav_{property_name}"
        context.eav_joins[alias] = {  # type: ignore[attr-defined]
            "property_name": property_name,
            "value_column": value_column,
            "events_alias": events_alias,
        }

    return node


def _get_events_alias(node: ast.SelectQuery) -> str | None:
    """Get the alias used for the events table in the query."""
    if not node.select_from:
        return None

    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        if isinstance(join.table, ast.Field):
            table_name = join.table.chain[0] if join.table.chain else None
            if table_name == "events":
                return join.alias or "events"
        join = join.next_join

    return None
