import dataclasses
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.errors import NotImplementedError
from posthog.hogql.visitor import Visitor
from hogvm.python.operation import (
    Operation,
    HOGQL_BYTECODE_IDENTIFIER,
    HOG_FUNCTIONS,
)

COMPARE_OPERATIONS = {
    ast.CompareOperationOp.Eq: Operation.EQ,
    ast.CompareOperationOp.NotEq: Operation.NOT_EQ,
    ast.CompareOperationOp.Gt: Operation.GT,
    ast.CompareOperationOp.GtEq: Operation.GT_EQ,
    ast.CompareOperationOp.Lt: Operation.LT,
    ast.CompareOperationOp.LtEq: Operation.LT_EQ,
    ast.CompareOperationOp.Like: Operation.LIKE,
    ast.CompareOperationOp.ILike: Operation.ILIKE,
    ast.CompareOperationOp.NotLike: Operation.NOT_LIKE,
    ast.CompareOperationOp.NotILike: Operation.NOT_ILIKE,
    ast.CompareOperationOp.In: Operation.IN,
    ast.CompareOperationOp.NotIn: Operation.NOT_IN,
    ast.CompareOperationOp.InCohort: Operation.IN_COHORT,
    ast.CompareOperationOp.NotInCohort: Operation.NOT_IN_COHORT,
    ast.CompareOperationOp.Regex: Operation.REGEX,
    ast.CompareOperationOp.NotRegex: Operation.NOT_REGEX,
    ast.CompareOperationOp.IRegex: Operation.IREGEX,
    ast.CompareOperationOp.NotIRegex: Operation.NOT_IREGEX,
}

ARITHMETIC_OPERATIONS = {
    ast.ArithmeticOperationOp.Add: Operation.PLUS,
    ast.ArithmeticOperationOp.Sub: Operation.MINUS,
    ast.ArithmeticOperationOp.Mult: Operation.MULTIPLY,
    ast.ArithmeticOperationOp.Div: Operation.DIVIDE,
    ast.ArithmeticOperationOp.Mod: Operation.MOD,
}


def to_bytecode(expr: str) -> list[Any]:
    from posthog.hogql.parser import parse_expr

    return create_bytecode(parse_expr(expr))


def create_bytecode(expr: ast.Expr | ast.Program, supported_functions=set[str]) -> list[Any]:
    bytecode = [HOGQL_BYTECODE_IDENTIFIER]
    bytecode.extend(BytecodeBuilder(supported_functions).visit(expr))
    return bytecode


@dataclasses.dataclass
class Local:
    name: str
    depth: int


class BytecodeBuilder(Visitor):
    def __init__(self, supported_functions=Optional[set[str]]):
        super().__init__()
        self.supported_functions = supported_functions or set()
        self.locals: list[Local] = []
        self.scope_depth = 0

    def _start_scope(self):
        self.scope_depth += 1

    def _end_scope(self):
        response = []
        self.scope_depth -= 1
        for local in reversed(self.locals):
            if local.depth <= self.scope_depth:
                break
            self.locals.pop()
            response.append(Operation.POP)
        return response

    def _declare_local(self, name: str):
        for local in reversed(self.locals):
            if local.depth < self.scope_depth:
                break
            if local.name == name:
                raise NotImplementedError(f"Variable `{name}` already declared in this scope")

        self.locals.append(Local(name, self.scope_depth))

    def visit_and(self, node: ast.And):
        response = []
        for expr in reversed(node.exprs):
            response.extend(self.visit(expr))
        response.append(Operation.AND)
        response.append(len(node.exprs))
        return response

    def visit_or(self, node: ast.Or):
        response = []
        for expr in reversed(node.exprs):
            response.extend(self.visit(expr))
        response.append(Operation.OR)
        response.append(len(node.exprs))
        return response

    def visit_not(self, node: ast.Not):
        return [*self.visit(node.expr), Operation.NOT]

    def visit_compare_operation(self, node: ast.CompareOperation):
        operation = COMPARE_OPERATIONS[node.op]
        if operation in [Operation.IN_COHORT, Operation.NOT_IN_COHORT]:
            raise NotImplementedError("Cohort operations are not supported")
        return [*self.visit(node.right), *self.visit(node.left), operation]

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        return [
            *self.visit(node.right),
            *self.visit(node.left),
            ARITHMETIC_OPERATIONS[node.op],
        ]

    def visit_field(self, node: ast.Field):
        if len(node.chain) == 1:
            for index, local in reversed(list(enumerate(self.locals))):
                if local.name == node.chain[0]:
                    return [Operation.GET_LOCAL, index]

        chain = []
        for element in reversed(node.chain):
            chain.extend([Operation.STRING, element])
        return [*chain, Operation.FIELD, len(node.chain)]

    def visit_tuple_access(self, node: ast.TupleAccess):
        return [Operation.INTEGER, node.index, Operation.FIELD, 1]

    def visit_array_access(self, node: ast.ArrayAccess):
        return [*self.visit(node.property), Operation.FIELD, 1]

    def visit_constant(self, node: ast.Constant):
        if node.value is True:
            return [Operation.TRUE]
        elif node.value is False:
            return [Operation.FALSE]
        elif node.value is None:
            return [Operation.NULL]
        elif isinstance(node.value, int):
            return [Operation.INTEGER, node.value]
        elif isinstance(node.value, float):
            return [Operation.FLOAT, node.value]
        elif isinstance(node.value, str):
            return [Operation.STRING, node.value]
        else:
            raise NotImplementedError(f"Constant type `{type(node.value)}` is not supported")

    def visit_call(self, node: ast.Call):
        if node.name == "not" and len(node.args) == 1:
            return [*self.visit(node.args[0]), Operation.NOT]
        if node.name == "and" and len(node.args) > 1:
            args = []
            for arg in reversed(node.args):
                args.extend(self.visit(arg))
            return [*args, Operation.AND, len(node.args)]
        if node.name == "or" and len(node.args) > 1:
            args = []
            for arg in reversed(node.args):
                args.extend(self.visit(arg))
            return [*args, Operation.OR, len(node.args)]
        if node.name not in HOG_FUNCTIONS and node.name not in self.supported_functions:
            raise NotImplementedError(f"HogQL function `{node.name}` is not supported")
        response = []
        for expr in reversed(node.args):
            response.extend(self.visit(expr))
        response.extend([Operation.CALL, node.name, len(node.args)])
        return response

    def visit_program(self, node: ast.Program):
        response = []
        self._start_scope()
        for expr in node.declarations:
            response.extend(self.visit(expr))
        response.extend(self._end_scope())
        return response

    def visit_block(self, node: ast.Block):
        response = []
        self._start_scope()
        for expr in node.declarations:
            response.extend(self.visit(expr))
        response.extend(self._end_scope())
        return response

    def visit_expr_statement(self, node: ast.ExprStatement):
        response = self.visit(node.expr)
        response.append(Operation.POP)
        return response

    def visit_return_statement(self, node: ast.ReturnStatement):
        if node.expr:
            response = self.visit(node.expr)
        else:
            response = [Operation.NULL]
        response.append(Operation.RETURN)
        return response

    def visit_if_statement(self, node: ast.IfStatement):
        expr = self.visit(node.expr)
        then = self.visit(node.then)
        else_ = self.visit(node.else_) if node.else_ else None

        response = []
        response.extend(expr)
        response.extend([Operation.JUMP_IF_FALSE, len(then) + 2])  # + else's OP_JUMP + count
        response.extend(then)
        if else_:
            response.extend([Operation.JUMP, len(else_)])
            response.extend(else_)

        return response

    def visit_while_statement(self, node: ast.WhileStatement):
        expr = self.visit(node.expr)
        body = self.visit(node.body)

        response = []
        response.extend(expr)
        response.extend([Operation.JUMP_IF_FALSE, len(body) + 2])  # + reverse jump
        response.extend(body)
        response.extend([Operation.JUMP, -len(response) - 2])
        return response

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        if node.is_declaration:
            self._declare_local(node.name)
            if node.expr:
                return self.visit(node.expr)
            return [Operation.NULL]
        else:
            for index, local in reversed(list(enumerate(self.locals))):
                if local.name == node.name:
                    return [*self.visit(node.expr), Operation.SET_LOCAL, index]
            raise NotImplementedError(f"Variable `{node.name}` not declared in this scope")
