from typing import TypeVar, cast, Optional, Any

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import Visitor, CloningVisitor
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WebStatsCombinedTable,
    WebBouncesCombinedTable,
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)

_T_AST = TypeVar("_T_AST", bound=AST)


class PreaggregatedTableValidator(Visitor[bool]):
    """Validates if a query can be transformed to use preaggregated tables."""

    def __init__(self, context: HogQLContext) -> None:
        self.context = context
        self.has_pageview_filter: bool = False
        self.has_unsupported_event: bool = False
        self.supported_aggregations: set[str] = set()
        self.supported_group_by_fields: set[str] = set()
        self.has_sample: bool = False
        self.sample_value: Optional[Any] = None

    def _is_person_id(self, field: ast.Field) -> bool:
        """Check if a field represents person_id in any of its forms."""
        return field.chain == ["person_id"] or field.chain == ["events", "person", "id"]

    def _is_session_id(self, field: ast.Field) -> bool:
        """Check if a field represents session_id in any of its forms."""
        return (
            field.chain == ["session", "id"]
            or field.chain == ["events", "$session_id"]
            or field.chain == ["$session_id"]
        )

    def visit_or(self, node: ast.Or) -> bool:
        # If any side is unsupported, the whole query is unsupported for preaggregation
        for expr in node.exprs:
            self.visit(expr)
        return True

    def visit_and(self, node: ast.And) -> bool:
        for expr in node.exprs:
            self.visit(expr)
        return True

    def visit_not(self, node: ast.Not) -> bool:
        self.visit(node.expr)
        return True

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_unknown(self, node: Any) -> bool:
        return True

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        # If select_from.table is a subquery, validate it recursively
        if (
            node.select_from
            and hasattr(node.select_from, "table")
            and isinstance(node.select_from.table, ast.SelectQuery)
        ):
            return self.visit(node.select_from.table)

        # Check FROM clause - must be from events table
        if not node.select_from or not isinstance(node.select_from.table, ast.Field):
            return False
        if node.select_from.table.chain != ["events"]:
            return False

        # Check WHERE clause for pageview filter
        if node.where:
            self.visit(node.where)

        # Check SAMPLE clause
        if node.select_from.sample:
            self.visit(node.select_from.sample)

        # Check SELECT clause for supported aggregations
        for expr in node.select:
            self.visit(expr)

        # Check GROUP BY clause
        if node.group_by:
            for expr in node.group_by:
                if isinstance(expr, ast.Field):
                    # Only allow group by fields that are supported
                    if len(expr.chain) >= 2 and expr.chain[0] == "properties":
                        property_name = expr.chain[1]
                        # Check if the property is in EVENT_PROPERTY_TO_FIELD mapping
                        if property_name not in EVENT_PROPERTY_TO_FIELD:
                            self.has_unsupported_event = True
                    elif len(expr.chain) >= 2 and expr.chain[0] == "session":
                        # Check if the session property is in SESSION_PROPERTY_TO_FIELD mapping
                        if len(expr.chain) >= 2 and expr.chain[1] not in SESSION_PROPERTY_TO_FIELD:
                            self.has_unsupported_event = True
                self.visit(expr)

        # Must have pageview filter and no unsupported events
        if not self.has_pageview_filter or self.has_unsupported_event:
            return False

        # Must have supported aggregations
        if not self.supported_aggregations:
            return False

        # If sample is specified, it must be 1
        if self.has_sample and self.sample_value != 1:
            return False

        # If sample is specified and is 1, treat as valid (allow preaggregation)
        return True

    def visit_subquery(self, node: ast.SelectQuery) -> bool:
        # For nested queries, just visit them
        return self.visit(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        # Check for event = '$pageview' or equals(event, '$pageview')
        if node.op == ast.CompareOperationOp.Eq:
            self.visit(node.left)
            self.visit(node.right)

            if (
                isinstance(node.left, ast.Field)
                and node.left.chain == ["event"]
                and isinstance(node.right, ast.Constant)
                and node.right.value == "$pageview"
            ):
                self.has_pageview_filter = True
            elif (
                isinstance(node.right, ast.Field)
                and node.right.chain == ["event"]
                and isinstance(node.left, ast.Constant)
                and node.left.value == "$pageview"
            ):
                self.has_pageview_filter = True
            elif (
                isinstance(node.left, ast.Field)
                and node.left.chain == ["event"]
                and isinstance(node.right, ast.Constant)
                and node.right.value != "$pageview"
            ):
                self.has_unsupported_event = True
            elif (
                isinstance(node.right, ast.Field)
                and node.right.chain == ["event"]
                and isinstance(node.left, ast.Constant)
                and node.left.value != "$pageview"
            ):
                self.has_unsupported_event = True

        return True

    def visit_call(self, node: ast.Call) -> bool:
        # Check for equals(event, '$pageview')
        if node.name == "equals" and len(node.args) == 2:
            if (
                isinstance(node.args[0], ast.Field)
                and node.args[0].chain == ["event"]
                and isinstance(node.args[1], ast.Constant)
            ):
                if node.args[1].value == "$pageview":
                    self.has_pageview_filter = True
                else:
                    self.has_unsupported_event = True

        # Check for supported aggregations
        elif node.name in ["count", "uniq"]:
            if node.name == "count":
                # Only count() and count(*) are supported for pageview counting
                if len(node.args) == 0:  # count()
                    self.supported_aggregations.add("pageviews_count_state")
                elif len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value == "*":
                    self.supported_aggregations.add("pageviews_count_state")
                # count(field) is not supported for preaggregation - fields should use uniq()
            elif node.name == "uniq":
                # Check what field is being counted
                if len(node.args) == 0:  # uniq() - not really valid but handle it
                    self.supported_aggregations.add("persons_uniq_state")
                elif len(node.args) == 1:
                    arg = node.args[0]
                    if isinstance(arg, ast.Field):
                        # Use helper functions to identify field types
                        if self._is_person_id(arg):
                            self.supported_aggregations.add("persons_uniq_state")
                        elif self._is_session_id(arg):
                            self.supported_aggregations.add("sessions_uniq_state")
                    elif isinstance(arg, ast.Constant) and arg.value == "*":
                        # uniq(*) - treat as person_id
                        self.supported_aggregations.add("persons_uniq_state")

        # Check for toStartOfDay function
        elif node.name == "toStartOfDay":
            self.supported_group_by_fields.add("toStartOfDay")

        return True

    def visit_field(self, node: ast.Field) -> bool:
        # Check for properties.x fields in GROUP BY
        if len(node.chain) >= 2 and node.chain[0] == "properties":
            property_name = node.chain[1]
            if property_name in EVENT_PROPERTY_TO_FIELD:
                self.supported_group_by_fields.add(f"properties.{property_name}")
        elif len(node.chain) >= 2 and node.chain[0] == "session":
            # Check for session properties
            if len(node.chain) >= 2 and node.chain[1] in SESSION_PROPERTY_TO_FIELD:
                self.supported_group_by_fields.add(f"session.{node.chain[1]}")

        return True

    def visit_constant(self, node: ast.Constant) -> bool:
        return True

    def visit_sample_expr(self, node: ast.SampleExpr) -> bool:
        self.has_sample = True
        if isinstance(node.sample_value, ast.Constant):
            self.sample_value = node.sample_value.value
        elif isinstance(node.sample_value, ast.RatioExpr):
            # Handle ratio expressions like "1" (which becomes RatioExpr with left=1, right=None)
            if node.sample_value.right is None:
                if isinstance(node.sample_value.left, ast.Constant):
                    self.sample_value = node.sample_value.left.value
        return True


class PreaggregatedTableTransformer(CloningVisitor):
    """Transforms a query to use preaggregated tables."""

    def __init__(self, context: HogQLContext, table_name: str) -> None:
        super().__init__()
        self.context = context
        self.table_name = table_name

    def _is_person_id(self, field: ast.Field) -> bool:
        """Check if a field represents person_id in any of its forms."""
        return field.chain == ["person_id"] or field.chain == ["events", "person", "id"]

    def _is_session_id(self, field: ast.Field) -> bool:
        """Check if a field represents session_id in any of its forms."""
        return (
            field.chain == ["session", "id"]
            or field.chain == ["events", "$session_id"]
            or field.chain == ["$session_id"]
        )

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Recursively transform subqueries in select_from (e.g. nested queries)
        new_select_from = None
        if node.select_from:
            join = self.visit(node.select_from)
            # Always create a new JoinExpr for preaggregated, with sample=None
            if isinstance(join, ast.JoinExpr) and isinstance(join.table, ast.Field) and join.table.chain == ["events"]:
                new_select_from = ast.JoinExpr(
                    table=ast.Field(chain=[self.table_name]),
                    alias=join.alias,
                    constraint=join.constraint,
                    next_join=join.next_join,
                    sample=None,
                )
            else:
                new_select_from = join

        # Transform SELECT clause
        new_select = [self.visit(expr) for expr in node.select]

        # Transform GROUP BY clause
        new_group_by = [self.visit(expr) for expr in node.group_by] if node.group_by else None

        return ast.SelectQuery(
            select=new_select,
            select_from=new_select_from,
            group_by=new_group_by,
            limit=node.limit,
            offset=node.offset,
            order_by=node.order_by,
            having=node.having,
        )

    def visit_call(self, node: ast.Call) -> ast.Expr:
        # Transform aggregations to use preaggregated state fields
        if node.name == "count":
            # count() and count(*) both become sumMerge(pageviews_count_state)
            return ast.Call(name="sumMerge", args=[ast.Field(chain=["pageviews_count_state"])])
        elif node.name == "uniq":
            if len(node.args) == 0:  # uniq() - treat as persons
                return ast.Call(name="uniqMerge", args=[ast.Field(chain=["persons_uniq_state"])])
            elif len(node.args) == 1:
                arg = node.args[0]
                if isinstance(arg, ast.Field):
                    # Use helper functions to identify field types
                    if self._is_person_id(arg):
                        return ast.Call(name="uniqMerge", args=[ast.Field(chain=["persons_uniq_state"])])
                    elif self._is_session_id(arg):
                        return ast.Call(name="uniqMerge", args=[ast.Field(chain=["sessions_uniq_state"])])
                elif isinstance(arg, ast.Constant) and arg.value == "*":
                    # uniq(*) - treat as persons
                    return ast.Call(name="uniqMerge", args=[ast.Field(chain=["persons_uniq_state"])])

        # Transform toStartOfDay to use period_bucket
        elif node.name == "toStartOfDay":
            if len(node.args) == 1 and isinstance(node.args[0], ast.Field) and node.args[0].chain == ["timestamp"]:
                return ast.Field(chain=["period_bucket"])

        return super().visit_call(node)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        # Transform properties.x to the corresponding field in the preaggregated table
        if len(node.chain) >= 2 and node.chain[0] == "properties":
            property_name = node.chain[1]
            if property_name in EVENT_PROPERTY_TO_FIELD:
                return ast.Field(chain=[EVENT_PROPERTY_TO_FIELD[property_name]])
        elif len(node.chain) >= 2 and node.chain[0] == "session":
            # Transform session properties
            if len(node.chain) >= 2 and node.chain[1] in SESSION_PROPERTY_TO_FIELD:
                return ast.Field(chain=[SESSION_PROPERTY_TO_FIELD[node.chain[1]]])

        return super().visit_field(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        # Recursively visit the table in the join
        new_table = self.visit(node.table) if node.table else None
        new_join = ast.JoinExpr(
            table=new_table,
            alias=node.alias,
            constraint=node.constraint,
            next_join=self.visit(node.next_join) if node.next_join else None,
            sample=None,  # Always remove sample if present
        )
        return new_join


def do_preaggregated_table_transforms(node: _T_AST, context: HogQLContext) -> _T_AST:
    """
    This function checks if the query can be transformed to use preaggregated tables.
    If it can, it returns the modified query; otherwise, it returns the original query.
    """
    # Only transform SelectQuery nodes
    if not isinstance(node, ast.SelectQuery):
        return node

    # Check if the query can be transformed
    validator = PreaggregatedTableValidator(context)
    is_valid = validator.visit(node)

    # Short-circuit if no transformations are valid
    if not is_valid:
        return node

    # Try WebStatsCombinedTable first, then WebBouncesCombinedTable
    tables_to_try = [
        ("web_stats_combined", WebStatsCombinedTable),
        ("web_bounces_combined", WebBouncesCombinedTable),
    ]

    for table_name, _table_class in tables_to_try:
        # For now, we'll use WebStatsCombinedTable for all valid queries
        # In the future, we could add logic to choose between tables based on the query
        if table_name == "web_stats_combined":
            transformer = PreaggregatedTableTransformer(context, table_name)
            return cast(_T_AST, transformer.visit(node))

    return node
