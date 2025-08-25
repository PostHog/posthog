from datetime import datetime, timedelta
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor, Visitor, clone_expr


def optimize_timestamp_conditions(node: ast.Expr, context: HogQLContext) -> ast.Expr:
    """
    Ensures all queries against the events table include toDate(timestamp) conditions
    for optimal index usage with ClickHouse.
    """
    return TimestampConditionOptimizer(context).visit(node)


class TimestampConditionOptimizer(TraversingVisitor):
    """
    AST transformer that adds toDate(timestamp) conditions to queries against the events table.
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

        # Check if we already have a toDate condition
        if self._has_todate_condition(node, events_alias):
            return

        # Extract existing timestamp conditions to determine date range
        date_range = self._extract_date_range_from_conditions(node, events_alias)

        # Add toDate conditions
        new_conditions = self._create_todate_conditions(events_alias, date_range)
        if new_conditions:
            node.where = self._add_conditions_to_where(node.where, new_conditions)

    def _find_events_table_alias(self, node: ast.SelectQuery) -> Optional[str]:
        """Find if the events table is used in this query and return its alias."""
        if not node.select_from:
            return None

        return EventsTableFinder().visit(node.select_from)

    def _has_todate_condition(self, node: ast.SelectQuery, table_alias: str) -> bool:
        """Check if the query already has a toDate(timestamp) condition."""
        if not node.where:
            return False

        return ToDateConditionChecker(table_alias).visit(node.where)

    def _extract_date_range_from_conditions(
        self, node: ast.SelectQuery, table_alias: str
    ) -> Optional[tuple[datetime, datetime]]:
        """Extract date range from existing timestamp conditions."""
        if not node.where:
            return None

        extractor = DateRangeExtractor(table_alias, self.context)
        return extractor.visit(node.where)

    def _create_todate_conditions(
        self, table_alias: str, date_range: Optional[tuple[datetime, datetime]]
    ) -> Optional[ast.Expr]:
        """Create toDate conditions based on the date range."""
        if date_range:
            start_date, end_date = date_range
        else:
            # Default to last 30 days if no date range found
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

        # Create the timestamp field reference
        timestamp_field = ast.Field(chain=[table_alias, "timestamp"]) if table_alias != "events" else ast.Field(chain=["timestamp"])

        # Create toDate(timestamp) expression
        todate_expr = ast.Call(name="toDate", args=[timestamp_field])

        # Create date constants
        start_date_str = start_date.date().isoformat()
        end_date_str = end_date.date().isoformat()

        # Create conditions: toDate(timestamp) >= start_date AND toDate(timestamp) <= end_date
        conditions = []

        # Start date condition
        if start_date:
            start_condition = ast.CompareOperation(
                op=CompareOperationOp.GtEq,
                left=clone_expr(todate_expr),
                right=ast.Call(name="toDate", args=[ast.Constant(value=start_date_str)])
            )
            conditions.append(start_condition)

        # End date condition
        if end_date:
            end_condition = ast.CompareOperation(
                op=CompareOperationOp.LtEq,
                left=clone_expr(todate_expr),
                right=ast.Call(name="toDate", args=[ast.Constant(value=end_date_str)])
            )
            conditions.append(end_condition)

        if len(conditions) == 1:
            return conditions[0]
        elif len(conditions) == 2:
            return ast.And(exprs=conditions)
        else:
            return None

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
        if node.type and hasattr(node.type, 'table_type'):
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


class ToDateConditionChecker(Visitor[bool]):
    """Checks if a WHERE clause already contains a toDate(timestamp) condition."""

    def __init__(self, table_alias: str):
        self.table_alias = table_alias

    def visit_and(self, node: ast.And) -> bool:
        return any(self.visit(expr) for expr in node.exprs)

    def visit_or(self, node: ast.Or) -> bool:
        return any(self.visit(expr) for expr in node.exprs)

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        # Check if either side has toDate(timestamp)
        return self._is_todate_timestamp(node.left) or self._is_todate_timestamp(node.right)

    def _is_todate_timestamp(self, expr: ast.Expr) -> bool:
        """Check if expression is toDate(timestamp) or toDate(table.timestamp)."""
        if not isinstance(expr, ast.Call) or expr.name != "toDate":
            return False

        if not expr.args or len(expr.args) != 1:
            return False

        arg = expr.args[0]
        if not isinstance(arg, ast.Field):
            return False

        # Check if it's the timestamp field from our table
        if len(arg.chain) == 1 and arg.chain[0] == "timestamp":
            return True
        elif len(arg.chain) == 2 and arg.chain[0] == self.table_alias and arg.chain[1] == "timestamp":
            return True

        return False

    def visit_call(self, node: ast.Call) -> bool:
        # Check nested calls
        return any(self.visit(arg) for arg in node.args if isinstance(arg, ast.Expr))

    def visit_field(self, node: ast.Field) -> bool:
        return False

    def visit_constant(self, node: ast.Constant) -> bool:
        return False


class DateRangeExtractor(Visitor[Optional[tuple[datetime, datetime]]]):
    """Extracts date range from timestamp conditions in WHERE clause."""

    def __init__(self, table_alias: str, context: HogQLContext):
        self.table_alias = table_alias
        self.context = context
        self.min_date: Optional[datetime] = None
        self.max_date: Optional[datetime] = None

    def visit_and(self, node: ast.And) -> Optional[tuple[datetime, datetime]]:
        for expr in node.exprs:
            self.visit(expr)
        return self._get_range()

    def visit_or(self, node: ast.Or) -> Optional[tuple[datetime, datetime]]:
        # For OR conditions, we can't reliably extract a single range
        return None

    def visit_compare_operation(self, node: ast.CompareOperation) -> Optional[tuple[datetime, datetime]]:
        # Check if this is a timestamp comparison
        timestamp_field = None
        value_expr = None

        if self._is_timestamp_field(node.left):
            timestamp_field = node.left
            value_expr = node.right
        elif self._is_timestamp_field(node.right):
            timestamp_field = node.right
            value_expr = node.left
            # Reverse the operation
            node.op = self._reverse_op(node.op)

        if timestamp_field and value_expr:
            # Try to extract date from value
            date_value = self._extract_date_value(value_expr)
            if date_value:
                self._update_range(node.op, date_value)

        return self._get_range()

    def _is_timestamp_field(self, expr: ast.Expr) -> bool:
        """Check if expression is the timestamp field from our table."""
        if not isinstance(expr, ast.Field):
            return False

        if len(expr.chain) == 1 and expr.chain[0] == "timestamp":
            return True
        elif len(expr.chain) == 2 and expr.chain[0] == self.table_alias and expr.chain[1] == "timestamp":
            return True

        return False

    def _extract_date_value(self, expr: ast.Expr) -> Optional[datetime]:
        """Extract datetime value from expression."""
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, str):
                try:
                    return datetime.fromisoformat(expr.value.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    pass
        elif isinstance(expr, ast.Call):
            # Handle functions like toDateTime, now(), etc.
            if expr.name in ["now", "today"]:
                return datetime.now()
            elif expr.name == "yesterday":
                return datetime.now() - timedelta(days=1)
            elif expr.name in ["toDateTime", "toDateTime64"] and expr.args:
                return self._extract_date_value(expr.args[0])

        return None

    def _update_range(self, op: CompareOperationOp, date: datetime) -> None:
        """Update the date range based on comparison operation."""
        if op in [CompareOperationOp.Gt, CompareOperationOp.GtEq]:
            if not self.min_date or date > self.min_date:
                self.min_date = date
        elif op in [CompareOperationOp.Lt, CompareOperationOp.LtEq]:
            if not self.max_date or date < self.max_date:
                self.max_date = date

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

    def _get_range(self) -> Optional[tuple[datetime, datetime]]:
        """Get the extracted date range."""
        if self.min_date and self.max_date:
            return (self.min_date, self.max_date)
        elif self.min_date:
            # If only min date, use current date as max
            return (self.min_date, datetime.now())
        elif self.max_date:
            # If only max date, use 30 days before as min
            return (self.max_date - timedelta(days=30), self.max_date)
        else:
            return None
