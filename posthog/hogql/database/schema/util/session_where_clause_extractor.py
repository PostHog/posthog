from typing import Optional

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp, ArithmeticOperationOp
from posthog.hogql.visitor import clone_expr, CloningVisitor, Visitor

SESSION_BUFFER_DAYS = 3


class SessionWhereClauseExtractor(CloningVisitor):
    def get_inner_where(self, parsed_query: ast.SelectQuery) -> Optional[ast.Expr]:
        if not parsed_query.where:
            return None

        # visit the where clause
        where = self.visit(parsed_query.where)

        if isinstance(where, ast.Constant):
            return None

        return clone_expr(where)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        is_left_constant = is_time_or_interval_constant(node.left)
        is_right_constant = is_time_or_interval_constant(node.right)
        is_left_timestamp_field = is_simple_timestamp_field_expression(node.left)
        is_right_timestamp_field = is_simple_timestamp_field_expression(node.right)

        if is_left_constant and is_right_constant:
            # just ignore this comparison
            return ast.Constant(value=True)

        # handle the left side being a min_timestamp expression and the right being constant
        if is_left_timestamp_field and is_right_constant:
            if node.op == CompareOperationOp.Eq:
                return ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.LtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Sub,
                                left=rewrite_timestamp_field(node.left),
                                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                            ),
                            right=node.right,
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=rewrite_timestamp_field(node.left),
                                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                            ),
                            right=node.right,
                        ),
                    ]
                )
            elif node.op == CompareOperationOp.Gt or node.op == CompareOperationOp.GtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=rewrite_timestamp_field(node.left),
                        right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                    ),
                    right=node.right,
                )
            elif node.op == CompareOperationOp.Lt or node.op == CompareOperationOp.LtEq:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Sub,
                        left=rewrite_timestamp_field(node.left),
                        right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=SESSION_BUFFER_DAYS)]),
                    ),
                    right=node.right,
                )
        elif is_right_timestamp_field and is_left_constant:
            # let's not duplicate the logic above, instead just flip and it and recurse
            if node.op in [
                CompareOperationOp.Eq,
                CompareOperationOp.Lt,
                CompareOperationOp.LtEq,
                CompareOperationOp.Gt,
                CompareOperationOp.GtEq,
            ]:
                return self.visit(
                    ast.CompareOperation(
                        op=CompareOperationOp.Eq
                        if node.op == CompareOperationOp.Eq
                        else CompareOperationOp.Lt
                        if node.op == CompareOperationOp.Gt
                        else CompareOperationOp.LtEq
                        if node.op == CompareOperationOp.GtEq
                        else CompareOperationOp.Gt
                        if node.op == CompareOperationOp.Lt
                        else CompareOperationOp.GtEq,
                        left=node.right,
                        right=node.left,
                    )
                )

        return ast.Constant(value=True)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        # don't even try to handle complex logic
        return ast.Constant(value=True)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if node.name == "and":
            return self.visit_and(ast.And(exprs=node.args))
        elif node.name == "or":
            return self.visit_or(ast.Or(exprs=node.args))
        return ast.Constant(value=True)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        return ast.Constant(value=True)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        raise Exception()  # this should never happen, as placeholders should be resolved before this runs

    def visit_and(self, node: ast.And) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]

        flattened = []
        for expr in exprs:
            if isinstance(expr, ast.And):
                flattened.extend(expr.exprs)
            else:
                flattened.append(expr)

        if any(isinstance(expr, ast.Constant) and expr.value is False for expr in flattened):
            return ast.Constant(value=False)

        filtered = [expr for expr in flattened if not isinstance(expr, ast.Constant) or expr.value is not True]
        if len(filtered) == 0:
            return ast.Constant(value=True)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.And(exprs=filtered)

    def visit_or(self, node: ast.Or) -> ast.Expr:
        exprs = [self.visit(expr) for expr in node.exprs]

        flattened = []
        for expr in exprs:
            if isinstance(expr, ast.Or):
                flattened.extend(expr.exprs)
            else:
                flattened.append(expr)

        if any(isinstance(expr, ast.Constant) and expr.value is True for expr in flattened):
            return ast.Constant(value=True)

        filtered = [expr for expr in flattened if not isinstance(expr, ast.Constant) or expr.value is not False]
        if len(filtered) == 0:
            return ast.Constant(value=False)
        elif len(filtered) == 1:
            return filtered[0]
        else:
            return ast.Or(exprs=filtered)

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def is_time_or_interval_constant(expr: ast.Expr) -> bool:
    return IsTimeOrIntervalConstantVisitor().visit(expr)


class IsTimeOrIntervalConstantVisitor(Visitor):
    def visit_constant(self, node: ast.Constant) -> bool:
        return True

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        return self.visit(node.left) and self.visit(node.right)

    def visit_call(self, node: ast.Call) -> bool:
        # some functions just return a constant
        if node.name in ["today", "now"]:
            return True
        # some functions return a constant if the first argument is a constant
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toTimeZone",
            "assumeNotNull",
            "toIntervalYear",
            "toIntervalMonth",
            "toIntervalWeek",
            "toIntervalDay",
            "toIntervalHour",
            "toIntervalMinute",
            "toIntervalSecond",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
        ]:
            return self.visit(node.args[0])

        if node.name in ["minus", "add"]:
            return all(self.visit(arg) for arg in node.args)

        # otherwise we don't know, so return False
        return False

    def visit_field(self, node: ast.Field) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)


def is_simple_timestamp_field_expression(expr: ast.Expr) -> bool:
    return IsSimpleTimestampFieldExpressionVisitor().visit(expr)


class IsSimpleTimestampFieldExpressionVisitor(Visitor):
    def visit_constant(self, node: ast.Constant) -> bool:
        return False

    def visit_field(self, node: ast.Field) -> bool:
        # this is quite leaky, as it doesn't handle aliases, but will handle all of posthog's hogql queries
        return (
            node.chain == ["min_timestamp"]
            or node.chain == ["sessions", "min_timestamp"]
            or node.chain == ["s", "min_timestamp"]
            or node.chain == ["timestamp"]
            or node.chain == ["events", "timestamp"]
            or node.chain == ["e", "timestamp"]
        )

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        # only allow the min_timestamp field to be used on one side of the arithmetic operation
        return (
            self.visit(node.left)
            and is_time_or_interval_constant(node.right)
            or (self.visit(node.right) and is_time_or_interval_constant(node.left))
        )

    def visit_call(self, node: ast.Call) -> bool:
        # some functions count as a timestamp field expression if their first argument is
        if node.name in [
            "parseDateTime64BestEffortOrNull",
            "toDateTime",
            "toTimeZone",
            "assumeNotNull",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
        ]:
            return self.visit(node.args[0])

        if node.name in ["minus", "add"]:
            return self.visit_arithmetic_operation(
                ast.ArithmeticOperation(
                    op=ArithmeticOperationOp.Sub if node.name == "minus" else ArithmeticOperationOp.Add,
                    left=node.args[0],
                    right=node.args[1],
                )
            )

        # otherwise we don't know, so return False
        return False

    def visit_compare_operation(self, node: ast.CompareOperation) -> bool:
        return False

    def visit_and(self, node: ast.And) -> bool:
        return False

    def visit_or(self, node: ast.Or) -> bool:
        return False

    def visit_not(self, node: ast.Not) -> bool:
        return False

    def visit_placeholder(self, node: ast.Placeholder) -> bool:
        raise Exception()

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)


def rewrite_timestamp_field(expr: ast.Expr) -> ast.Expr:
    return RewriteTimestampFieldVisitor().visit(expr)


class RewriteTimestampFieldVisitor(CloningVisitor):
    def visit_field(self, node: ast.Field) -> ast.Field:
        # this is quite leaky, as it doesn't handle aliases, but will handle all of posthog's hogql queries
        if (
            node.chain == ["min_timestamp"]
            or node.chain == ["sessions", "min_timestamp"]
            or node.chain == ["s", "min_timestamp"]
        ):
            return ast.Field(chain=["raw_sessions", "min_timestamp"])
        elif node.chain == ["timestamp"] or node.chain == ["events", "timestamp"] or node.chain == ["e", "timestamp"]:
            return ast.Field(chain=["raw_sessions", "min_timestamp"])
        return node

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)
