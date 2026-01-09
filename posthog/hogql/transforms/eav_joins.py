"""
EAV (Entity-Attribute-Value) join transform for event properties.

This module provides functions for handling EAV-materialized properties in HogQL.
It finds EAV properties in queries and marks them for special handling by the printer.
"""

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


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


class EAVJoinRewriter(CloningVisitor):
    """Rewrite Field nodes that have PropertyType to use EAV joined tables.

    Note: We override visit_field instead of visit_property_type because
    CloningVisitor doesn't recursively visit type annotations.
    """

    def __init__(
        self,
        context: HogQLContext,
        eav_aliases: dict[str, str],  # property_name -> table_alias
    ):
        super().__init__(clear_types=False)
        self.context = context
        self.eav_aliases = eav_aliases

    def visit_field(self, node: ast.Field):
        # First create the cloned field using parent method
        field = super().visit_field(node)

        # Check if this field's type is a PropertyType that needs EAV handling
        if not isinstance(node.type, ast.PropertyType):
            return field

        type_node = node.type

        if not self.context.property_swapper:
            return field

        if type_node.field_type.name != "properties" or len(type_node.chain) != 1:
            return field

        if not isinstance(type_node.field_type.table_type, ast.BaseTableType):
            return field

        table_type = type_node.field_type.table_type
        table_name = table_type.resolve_database_table(self.context).to_printed_hogql()

        if table_name != "events":
            return field

        property_name = str(type_node.chain[0])

        if property_name not in self.eav_aliases:
            return field

        prop_info = self.context.property_swapper.event_properties.get(property_name, {})
        eav_column = prop_info.get("eav")

        if not eav_column:
            return field

        alias = self.eav_aliases[property_name]

        # Create a new PropertyType with EAV metadata
        new_type = ast.PropertyType(
            chain=type_node.chain,
            field_type=type_node.field_type,
        )
        new_type.eav_alias = alias  # type: ignore[attr-defined]
        new_type.eav_column = eav_column  # type: ignore[attr-defined]

        field.type = new_type
        return field


def add_eav_joins(node: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """
    Process a SelectQuery for EAV materialized event properties.

    This function:
    1. Finds all event properties that have EAV materialization enabled
    2. Stores EAV JOIN info in the context for the printer to use
    3. Rewrites PropertyType nodes to reference the EAV table columns
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

    # Create aliases for each EAV property
    # The printer will handle backtick escaping for special characters
    eav_aliases: dict[str, str] = {}
    for property_name in finder.eav_properties.keys():
        eav_aliases[property_name] = f"eav_{property_name}"

    # Store EAV join info in context for the printer to use
    # The printer will generate the actual JOIN SQL
    if not hasattr(context, "eav_joins"):
        context.eav_joins = {}  # type: ignore[attr-defined]
    context.eav_joins.update(  # type: ignore[attr-defined]
        {
            alias: {
                "property_name": prop_name,
                "value_column": finder.eav_properties[prop_name],
                "events_alias": events_alias,
            }
            for prop_name, alias in eav_aliases.items()
        }
    )

    # Rewrite PropertyType nodes to use the EAV aliases
    rewriter = EAVJoinRewriter(context, eav_aliases)
    node = rewriter.visit(node)

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
