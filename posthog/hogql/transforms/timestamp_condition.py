from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor, Visitor, clone_expr


def optimize_timestamp_conditions(node: ast.Expr, context: HogQLContext):
    """
    For each condition on timestamp column in events table queries,
    adds a corresponding toDate(timestamp) condition checking only the date.
    """
    TimestampConditionOptimizer(context).visit(node)


class TimestampConditionOptimizer(TraversingVisitor):
    """
    For each condition on timestamp column in events table queries,
    adds a corresponding toDate(timestamp) condition checking only the date.
    This optimization leverages ClickHouse's index on (team_id, toDate(timestamp), ...).
    """

    def __init__(self, context: HogQLContext):
        self.context = context
        self.events_table_alias: Optional[str] = None

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        # Check if this query uses the events table
        events_alias = self._find_events_table_alias(node)
        if not events_alias:
            return

        # Find all timestamp conditions and add corresponding toDate conditions
        if node.where:
            timestamp_conditions = self._find_timestamp_conditions(node.where, events_alias)
            for condition in timestamp_conditions:
                date_condition = self._create_date_condition_from_timestamp(condition, events_alias)
                if date_condition:
                    node.where = self._add_conditions_to_where(node.where, date_condition)

    def _find_events_table_alias(self, node: ast.SelectQuery) -> Optional[str]:
        """Find if the events table is used in this query and return its alias."""
        if not node.select_from:
            return None

        return EventsTableFinder().visit(node.select_from)

    def _find_timestamp_conditions(self, where: ast.Expr, table_alias: str) -> list[ast.CompareOperation]:
        """Find all conditions that filter on timestamp column."""
        finder = TimestampConditionFinder(table_alias)
        return finder.visit(where)

    def _create_date_condition_from_timestamp(
        self, timestamp_condition: ast.CompareOperation, table_alias: str
    ) -> Optional[ast.Expr]:
        """Create a corresponding toDate(timestamp) condition from a timestamp condition."""
        # Check which side of the comparison is the timestamp field
        timestamp_field = None
        value_expr = None
        op = timestamp_condition.op

        if self._is_timestamp_field(timestamp_condition.left, table_alias):
            timestamp_field = timestamp_condition.left
            value_expr = timestamp_condition.right
        elif self._is_timestamp_field(timestamp_condition.right, table_alias):
            timestamp_field = timestamp_condition.right
            value_expr = timestamp_condition.left
            # Reverse the operation when timestamp is on the right
            op = self._reverse_op(op)

        if not timestamp_field or not value_expr:
            return None

        # Create toDate(timestamp) field
        todate_timestamp = ast.Call(name="toDate", args=[clone_expr(timestamp_field)])

        # Create toDate(value) or extract date from value
        todate_value = self._create_todate_value(value_expr)
        if not todate_value:
            return None

        # Convert operator for date comparison
        date_op = self._convert_op_for_date(op)

        # Create the date condition
        return ast.CompareOperation(op=date_op, left=todate_timestamp, right=todate_value)

    def _is_timestamp_field(self, expr: ast.Expr, table_alias: str) -> bool:
        """Check if expression is the timestamp field from our table."""
        if not isinstance(expr, ast.Field):
            return False

        if len(expr.chain) == 1 and expr.chain[0] == "timestamp":
            return True
        elif len(expr.chain) == 2 and expr.chain[0] == table_alias and expr.chain[1] == "timestamp":
            return True

        return False

    def _create_todate_value(self, value_expr: ast.Expr) -> Optional[ast.Expr]:
        """Create toDate(value) expression from the value side of timestamp comparison."""
        if isinstance(value_expr, ast.Constant) and isinstance(value_expr.value, str):
            # For string constants, wrap in toDate
            return ast.Call(name="toDate", args=[clone_expr(value_expr)])
        elif isinstance(value_expr, ast.Call):
            # For function calls, might already be date functions or need wrapping
            if value_expr.name in ["now", "today", "yesterday"]:
                return ast.Call(name="toDate", args=[clone_expr(value_expr)])
            elif value_expr.name in ["toDate", "toDateTime", "toDateTime64"]:
                # Already a date/time function, extract the date part
                return ast.Call(name="toDate", args=[clone_expr(value_expr)])

        # For other expressions, try wrapping in toDate
        return ast.Call(name="toDate", args=[clone_expr(value_expr)])

    def _convert_op_for_date(self, op: CompareOperationOp) -> CompareOperationOp:
        """Convert timestamp operators to appropriate date operators."""
        # For date comparisons, > becomes >= and < becomes <= for proper boundary handling
        if op == CompareOperationOp.Gt:
            return CompareOperationOp.GtEq
        elif op == CompareOperationOp.Lt:
            return CompareOperationOp.LtEq
        else:
            return op

    def _reverse_op(self, op: CompareOperationOp) -> CompareOperationOp:
        """Reverse comparison operation."""
        reverse_map = {
            CompareOperationOp.Gt: CompareOperationOp.Lt,
            CompareOperationOp.GtEq: CompareOperationOp.LtEq,
            CompareOperationOp.Lt: CompareOperationOp.Gt,
            CompareOperationOp.LtEq: CompareOperationOp.GtEq,
            CompareOperationOp.Eq: CompareOperationOp.Eq,
            CompareOperationOp.NotEq: CompareOperationOp.NotEq,
        }
        return reverse_map.get(op, op)

    def _add_conditions_to_where(self, where: Optional[ast.Expr], new_conditions: ast.Expr) -> ast.Expr:
        """Add new conditions to the WHERE clause."""
        if not where:
            return new_conditions

        # If WHERE is already an AND, add to it
        if isinstance(where, ast.And):
            where.exprs.append(new_conditions)
            return where
        else:
            # Otherwise create a new AND
            return ast.And(exprs=[where, new_conditions])


class TimestampConditionFinder(Visitor[list[ast.CompareOperation]]):
    """Finds all conditions that filter on the timestamp column."""

    def __init__(self, table_alias: str):
        self.table_alias = table_alias
        self.conditions: list[ast.CompareOperation] = []

    def visit_and(self, node: ast.And) -> list[ast.CompareOperation]:
        for expr in node.exprs:
            self.visit(expr)
        return self.conditions

    def visit_or(self, node: ast.Or) -> list[ast.CompareOperation]:
        # For OR conditions, we still want to optimize each branch
        for expr in node.exprs:
            self.visit(expr)
        return self.conditions

    def visit_compare_operation(self, node: ast.CompareOperation) -> list[ast.CompareOperation]:
        # Check if this comparison involves the timestamp field
        if self._is_timestamp_field(node.left) or self._is_timestamp_field(node.right):
            # Check that this isn't already a toDate condition
            if not self._is_todate_condition(node):
                self.conditions.append(node)
        return self.conditions

    def _is_timestamp_field(self, expr: ast.Expr) -> bool:
        """Check if expression is the timestamp field from our table."""
        if not isinstance(expr, ast.Field):
            return False

        if len(expr.chain) == 1 and expr.chain[0] == "timestamp":
            return True
        elif len(expr.chain) == 2 and expr.chain[0] == self.table_alias and expr.chain[1] == "timestamp":
            return True

        return False

    def _is_todate_condition(self, node: ast.CompareOperation) -> bool:
        """Check if this is already a toDate(timestamp) condition."""
        return self._is_todate_timestamp_expr(node.left) or self._is_todate_timestamp_expr(node.right)

    def _is_todate_timestamp_expr(self, expr: ast.Expr) -> bool:
        """Check if expression is toDate(timestamp) or toDate(table.timestamp)."""
        if not isinstance(expr, ast.Call) or expr.name != "toDate":
            return False

        if not expr.args or len(expr.args) != 1:
            return False

        return self._is_timestamp_field(expr.args[0])


class EventsTableFinder(Visitor[Optional[str]]):
    """Finds the events table in a FROM clause and returns its alias."""

    def visit_join_expr(self, node: ast.JoinExpr) -> Optional[str]:
        # Check the main table
        result = self.visit(node.table)
        if result:
            return result

        # Check next join if exists
        if node.next_join:
            return self.visit(node.next_join)

        return None

    def visit_select_query(self, node: ast.SelectQuery) -> Optional[str]:
        # For subqueries, we don't look inside
        return None

    def visit_field(self, node: ast.Field) -> Optional[str]:
        # Check if this is the events table
        if node.type and hasattr(node.type, "table_type"):
            table_type = node.type.table_type
            if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
                # Return the alias or table name
                if isinstance(table_type, ast.TableAliasType):
                    return table_type.alias
                return "events"

        # Check by name if no type info
        if node.chain and node.chain[0] == "events":
            return "events"

        return None

    def visit_table_expr(self, node: ast.Table) -> Optional[str]:
        # Check if this is the events table by checking the table name
        from posthog.hogql.database.schema.events import EventsTable

        if node.type and isinstance(node.type, ast.TableType) and isinstance(node.type.table, EventsTable):
            return node.alias or "events"
        return None

    def visit_table_alias_expr(self, node: ast.TableAliasType) -> Optional[str]:
        return self.visit_table_expr(node.table)
