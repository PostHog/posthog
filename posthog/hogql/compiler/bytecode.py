import dataclasses
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_program
from posthog.hogql.visitor import Visitor

from common.hogvm.python.execute import BytecodeResult, execute_bytecode
from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, HOGQL_BYTECODE_VERSION, Operation
from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL

if TYPE_CHECKING:
    from posthog.models import Team

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


@dataclasses.dataclass
class Local:
    name: str
    depth: int
    is_captured: bool


@dataclasses.dataclass
class HogFunction:
    name: str
    params: list[str]
    bytecode: list[Any]


class UpValue:
    def __init__(self, index: int, is_local: bool):
        self.index = index
        self.is_local = is_local


@dataclasses.dataclass
class CompiledBytecode:
    bytecode: list[Any]
    locals: list[Local]
    upvalues: list[UpValue]


def to_bytecode(expr: str) -> list[Any]:
    from posthog.hogql.parser import parse_expr

    return create_bytecode(parse_expr(expr)).bytecode


def create_bytecode(
    expr: ast.Expr | ast.Statement | ast.Program,
    supported_functions: Optional[set[str]] = None,
    args: Optional[list[str]] = None,
    context: Optional[HogQLContext] = None,
    enclosing: Optional["BytecodeCompiler"] = None,
    in_repl: Optional[bool] = False,
    locals: Optional[list[Local]] = None,
    cohort_membership_supported: Optional[bool] = False,
) -> CompiledBytecode:
    supported_functions = supported_functions or set()
    bytecode: list[Any] = []
    if args is None:
        bytecode.append(HOGQL_BYTECODE_IDENTIFIER)
        bytecode.append(HOGQL_BYTECODE_VERSION)
    compiler = BytecodeCompiler(
        supported_functions, args, context, enclosing, in_repl, locals, cohort_membership_supported
    )
    bytecode.extend(compiler.visit(expr))
    return CompiledBytecode(bytecode, locals=compiler.locals, upvalues=compiler.upvalues)


class BytecodeCompiler(Visitor):
    mode: Literal["hog", "ast"]

    def __init__(
        self,
        supported_functions: Optional[set[str]] = None,
        args: Optional[list[str]] = None,
        context: Optional[HogQLContext] = None,
        enclosing: Optional["BytecodeCompiler"] = None,
        in_repl: Optional[bool] = False,
        locals: Optional[list[Local]] = None,
        cohort_membership_supported: Optional[bool] = False,
    ):
        super().__init__()
        self.enclosing = enclosing
        self.mode = enclosing.mode if enclosing else "hog"
        self.supported_functions = supported_functions or set()
        self.in_repl = in_repl
        self.locals: list[Local] = locals or []
        self.upvalues: list[UpValue] = []
        self.scope_depth = 0
        self.args = args
        self.cohort_membership_supported = cohort_membership_supported
        # we're in a function definition
        if args is not None:
            for arg in args:
                self._declare_local(arg)
        self.context = context or HogQLContext(team_id=None)

    def _start_scope(self):
        self.scope_depth += 1

    def _end_scope(self) -> list[Any]:
        self.scope_depth -= 1
        if self.in_repl and self.scope_depth == 0:
            return []

        response: list[Any] = []
        for local in reversed(self.locals):
            if local.depth <= self.scope_depth:
                break
            self.locals.pop()
            if local.is_captured:
                response.append(Operation.CLOSE_UPVALUE)
            else:
                response.append(Operation.POP)
        return response

    def _declare_local(self, name: str) -> int:
        for local in reversed(self.locals):
            if local.depth < self.scope_depth:
                break
            if local.name == name:
                raise QueryError(f"Variable `{name}` already declared in this scope")

        self.locals.append(Local(name=name, depth=self.scope_depth, is_captured=False))
        return len(self.locals) - 1

    def visit(self, node: ast.AST | None):
        # In "hog" mode we compile AST nodes to bytecode.
        # In "ast" mode we pass through as they are.
        # You may enter "ast" mode with `sql()` or `(select ...)`
        if self.mode == "hog" or isinstance(node, ast.Placeholder):
            return super().visit(node)
        return self._visit_hog_ast(node)

    def visit_and(self, node: ast.And):
        response = []
        for expr in node.exprs:
            response.extend(self.visit(expr))
        response.append(Operation.AND)
        response.append(len(node.exprs))
        return response

    def visit_or(self, node: ast.Or):
        response = []
        for expr in node.exprs:
            response.extend(self.visit(expr))
        response.append(Operation.OR)
        response.append(len(node.exprs))
        return response

    def visit_not(self, node: ast.Not):
        return [*self.visit(node.expr), Operation.NOT]

    def visit_compare_operation(self, node: ast.CompareOperation):
        operation = COMPARE_OPERATIONS[node.op]
        if operation in [Operation.IN_COHORT, Operation.NOT_IN_COHORT]:
            if self.cohort_membership_supported:
                if operation == Operation.IN_COHORT:
                    return self.visit(ast.Call(name="inCohort", args=[node.right]))
                else:
                    return self.visit(ast.Call(name="notInCohort", args=[node.right]))
            else:
                cohort_name = ""
                if isinstance(node.right, ast.Constant):
                    if isinstance(node.right.value, int):
                        cohort_name = f" (cohort id={node.right.value})"
                    else:
                        cohort_name = f" (cohort: {str(node.right.value)})"
                raise QueryError(
                    f"Can't use cohorts in real-time filters. Please inline the relevant expressions{cohort_name}."
                )
        return [*self.visit(node.right), *self.visit(node.left), operation]

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        return [
            *self.visit(node.right),
            *self.visit(node.left),
            ARITHMETIC_OPERATIONS[node.op],
        ]

    def _add_upvalue(self, index: int, is_local: bool) -> int:
        for i, upvalue in enumerate(self.upvalues):
            if upvalue.index == index and upvalue.is_local == is_local:
                return i
        self.upvalues.append(UpValue(index, is_local))
        return len(self.upvalues) - 1

    def _resolve_upvalue(self, name: str) -> int:
        if not self.enclosing:
            return -1

        for index, local in reversed(list(enumerate(self.enclosing.locals))):
            if local.name == name:
                local.is_captured = True
                return self._add_upvalue(index, True)

        upvalue = self.enclosing._resolve_upvalue(name)
        if upvalue != -1:
            return self._add_upvalue(upvalue, False)

        return -1

    def visit_field(self, node: ast.Field):
        ops: list[str | int] = []
        for index, local in reversed(list(enumerate(self.locals))):
            if local.name == node.chain[0]:
                ops = [Operation.GET_LOCAL, index]
                break

        if len(ops) == 0:
            arg = self._resolve_upvalue(str(node.chain[0]))
            if arg != -1:
                ops = [Operation.GET_UPVALUE, arg]

        if len(ops) > 0:
            if len(node.chain) > 1:
                for element in node.chain[1:]:
                    if isinstance(element, int):
                        ops.extend([Operation.INTEGER, element, Operation.GET_PROPERTY])
                    else:
                        ops.extend([Operation.STRING, str(element), Operation.GET_PROPERTY])
            return ops

        # Did not find a local nor an upvalue, must be a global.

        chain = []
        for element in reversed(node.chain):
            chain.extend([Operation.STRING, element])
        if self.context.globals and node.chain[0] in self.context.globals:
            self.context.add_notice(start=node.start, end=node.end, message="Global variable: " + str(node.chain[0]))
        else:
            self.context.add_warning(
                start=node.start, end=node.end, message="Unknown global variable: " + str(node.chain[0])
            )
        return [*chain, Operation.GET_GLOBAL, len(node.chain)]

    def visit_tuple_access(self, node: ast.TupleAccess):
        return [
            *self.visit(node.tuple),
            Operation.INTEGER,
            node.index,
            Operation.GET_PROPERTY_NULLISH if node.nullish else Operation.GET_PROPERTY,
        ]

    def visit_array_access(self, node: ast.ArrayAccess):
        if (
            isinstance(node.property, ast.Constant)
            and isinstance(node.property.value, int)
            and node.property.value == 0
        ):
            raise QueryError("Array access starts from 1")
        return [
            *self.visit(node.array),
            *self.visit(node.property),
            Operation.GET_PROPERTY_NULLISH if node.nullish else Operation.GET_PROPERTY,
        ]

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
            raise QueryError(f"Constant type `{type(node.value)}` is not supported")

    def visit_call(self, node: ast.Call):
        if node.name == "not" and len(node.args) == 1:
            return [*self.visit(node.args[0]), Operation.NOT]
        if node.name == "and" and len(node.args) > 1:
            args = []
            for arg in node.args:
                args.extend(self.visit(arg))
            return [*args, Operation.AND, len(node.args)]
        if node.name == "or" and len(node.args) > 1:
            args = []
            for arg in node.args:
                args.extend(self.visit(arg))
            return [*args, Operation.OR, len(node.args)]
        if node.name == "if" and len(node.args) >= 2:
            expr = self.visit(node.args[0])
            then = self.visit(node.args[1])
            else_ = self.visit(node.args[2]) if len(node.args) == 3 else None
            response = []
            response.extend(expr)
            response.extend([Operation.JUMP_IF_FALSE, len(then) + (2 if else_ else 0)])
            response.extend(then)
            if else_:
                response.extend([Operation.JUMP, len(else_)])
                response.extend(else_)
            return response
        if node.name == "multiIf" and len(node.args) >= 2:
            if len(node.args) <= 3:
                return self.visit(ast.Call(name="if", args=node.args))
            prev = None if len(node.args) % 2 == 0 else self.visit(node.args[-1])
            for i in range(len(node.args) - 2 - (len(node.args) % 2), -1, -2):
                expr = self.visit(node.args[i])
                then = self.visit(node.args[i + 1])
                response = []
                response.extend(expr)
                response.extend([Operation.JUMP_IF_FALSE, len(then) + (2 if prev else 0)])
                response.extend(then)
                if prev:
                    response.extend([Operation.JUMP, len(prev)])
                    response.extend(prev)
                prev = response
            return prev
        if node.name == "ifNull" and len(node.args) == 2:
            expr = self.visit(node.args[0])
            if_null = self.visit(node.args[1])
            response = []
            response.extend(expr)
            response.extend([Operation.JUMP_IF_STACK_NOT_NULL, len(if_null) + 1])
            response.extend([Operation.POP])
            response.extend(if_null)
            return response
        if node.name == "sql" and len(node.args) == 1:
            prev_mode = self.mode
            self.mode = "ast"
            try:
                response = self.visit(node.args[0])
            finally:
                self.mode = prev_mode
            return response

        # HogQL functions can have two sets of parameters: asd(args) or asd(params)(args)
        # If params exist, take them as the first set
        args = node.params if node.params is not None else node.args

        response = []
        for expr in args:
            response.extend(self.visit(expr))

        found_local_with_name = False
        for local in reversed(self.locals):
            if local.name == node.name:
                found_local_with_name = True

        if found_local_with_name:
            field = self.visit(ast.Field(chain=[node.name]))
            response.extend([*field, Operation.CALL_LOCAL, len(args)])
        else:
            upvalue = self._resolve_upvalue(node.name)
            if upvalue != -1:
                response.extend([Operation.GET_UPVALUE, upvalue, Operation.CALL_LOCAL, len(args)])
            else:
                if self.context.globals and node.name in self.context.globals:
                    self.context.add_notice(
                        start=node.start, end=node.end, message="Global variable: " + str(node.name)
                    )
                elif node.name in self.supported_functions or node.name in STL or node.name in BYTECODE_STL:
                    pass
                else:
                    self.context.add_error(
                        start=node.start, end=node.end, message=f"Hog function `{node.name}` is not implemented"
                    )

                response.extend([Operation.CALL_GLOBAL, node.name, len(args)])

        # If the node has two sets of params, process the second set now
        if node.params is not None:
            next_response = []
            for expr in node.args:
                next_response.extend(self.visit(expr))
            response = [*next_response, *response, Operation.CALL_LOCAL, len(node.args)]

        return response

    def visit_expr_call(self, node: ast.ExprCall):
        response = []
        for expr in node.args:
            response.extend(self.visit(expr))
        response.extend(self.visit(node.expr))
        response.extend([Operation.CALL_LOCAL, len(node.args)])
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
        if node.expr is None:
            return []
        if isinstance(node.expr, ast.CompareOperation) and node.expr.op == ast.CompareOperationOp.Eq:
            self.context.add_warning(
                start=node.start,
                end=node.end,
                message="You must use ':=' for assignment instead of '='.",
            )
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

    def visit_throw_statement(self, node: ast.ThrowStatement):
        return [*self.visit(node.expr), Operation.THROW]

    def visit_try_catch_statement(self, node: ast.TryCatchStatement):
        if node.finally_stmt:
            raise QueryError("finally blocks are not yet supported")
        if not node.catches or len(node.catches) == 0:
            raise QueryError("try statement must have at least one catch block")

        try_stmt = self.visit(node.try_stmt)
        response = []
        response.extend(
            [
                Operation.TRY,
                len(try_stmt) + 2 + 2,
            ]
        )
        response.extend(try_stmt)
        response.append(Operation.POP_TRY)

        set_end_positions = []
        catches_bytecode = []
        self._start_scope()
        self._declare_local("e")  # common error var for all blocks
        catches_bytecode.extend(self.visit(ast.Field(chain=["e", "type"])))
        self._declare_local("type")  # common error var for all blocks
        # catches_bytecode.extend(self.visit(ast.Field(chain=['e'])))
        for catch in node.catches:
            catch_var = catch[0] or "e"
            catch_type = catch[1] or "Error"
            catch_stmt = catch[2]

            self._start_scope()

            # If we catch all
            if catch_type == "Error":
                if catch_var != "e":
                    self._declare_local(catch_var)
                    catches_bytecode.extend(self.visit(ast.Field(chain=["e"])))
                # Add the catch block
                catches_bytecode.extend(self.visit(catch_stmt))
                catches_bytecode.extend(self._end_scope())
                # And then jump to the very end, skipping everything else
                catches_bytecode.extend([Operation.JUMP, None])
                set_end_positions.append(len(catches_bytecode) - 1)
            else:
                # Named catch (e: RetryError) {}
                compare_bytecode = self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["type"]),
                        right=ast.Constant(value=catch_type),
                    )
                )
                catches_bytecode.extend(
                    [
                        *compare_bytecode,
                        Operation.JUMP_IF_FALSE,  # we add the jump position later
                    ]
                )

                catch_bytecode = []
                if catch_var != "e":
                    self._declare_local(catch_var)
                    catch_bytecode.extend(self.visit(ast.Field(chain=["e"])))
                catch_bytecode.extend(self.visit(catch_stmt))

                end_scope = self._end_scope()
                catch_bytecode.extend(end_scope)

                catches_bytecode.extend(
                    [
                        len(catch_bytecode) + 2 - len(end_scope),  # the jump position from earlier
                        *catch_bytecode,
                        Operation.JUMP,
                        None,
                    ]
                )
                set_end_positions.append(len(catches_bytecode) - 1)

        # re-raise if nothing matched
        catches_bytecode.extend(
            [
                Operation.POP,  # pop the type
                Operation.THROW,  # throw the error
            ]
        )
        end_scope = self._end_scope()
        catches_bytecode.extend(end_scope)

        for position in set_end_positions:
            catches_bytecode[position] = len(catches_bytecode) - position - len(end_scope) - 1

        response.extend([Operation.JUMP, len(catches_bytecode)])
        response.extend(catches_bytecode)
        return response

    def visit_if_statement(self, node: ast.IfStatement):
        expr = self.visit(node.expr)
        then = self.visit(node.then)
        else_ = self.visit(node.else_) if node.else_ else None

        response = []
        response.extend(expr)
        response.extend([Operation.JUMP_IF_FALSE, len(then) + (2 if else_ else 0)])
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

    def visit_for_statement(self, node: ast.ForStatement):
        if node.initializer:
            self._start_scope()

        initializer = self.visit(node.initializer) or []
        condition = self.visit(node.condition) or []
        increment = self.visit(node.increment) or []
        body = self.visit(node.body) or []

        response: list = []
        response.extend(initializer)
        response.extend(condition)
        response.extend([Operation.JUMP_IF_FALSE, len(body) + len(increment) + 2])
        response.extend(body)
        response.extend(increment)
        response.extend([Operation.JUMP, -len(increment) - len(body) - 2 - len(condition) - 2])

        if node.initializer:
            response.extend(self._end_scope())
        return response

    def visit_for_in_statement(self, node: ast.ForInStatement):
        response: list = []
        self._start_scope()

        key_var = node.keyVar
        value_var = node.valueVar

        # set up a bunch of temporary variables
        expr_local = self._declare_local("__H_expr_H__")  # the obj/array itself
        response.extend(self.visit(node.expr))

        if key_var is not None:
            expr_keys_local = self._declare_local("__H_keys_H__")  # keys
            response.extend([Operation.GET_LOCAL, expr_local, Operation.CALL_GLOBAL, "keys", 1])
        else:
            expr_keys_local = None

        expr_values_local = self._declare_local("__H_values_H__")  # values
        response.extend([Operation.GET_LOCAL, expr_local, Operation.CALL_GLOBAL, "values", 1])

        loop_index_local = self._declare_local("__H_index_H__")  # 0
        response.extend([Operation.INTEGER, 1])

        loop_limit_local = self._declare_local("__H_limit_H__")  # length of keys
        response.extend(
            [
                Operation.GET_LOCAL,
                expr_values_local,
                Operation.CALL_GLOBAL,
                "length",
                1,
            ]
        )

        if key_var is not None:
            key_var_local = self._declare_local(key_var)  # loop key
            response.extend([Operation.NULL])
        else:
            key_var_local = None

        value_var_local = self._declare_local(value_var)  # loop value
        response.extend([Operation.NULL])

        # check if loop_index < loop_limit
        condition = [Operation.GET_LOCAL, loop_limit_local, Operation.GET_LOCAL, loop_index_local, Operation.LT_EQ]

        # set key_var and value_var
        body: list = []
        if key_var is not None:
            body.extend(
                [
                    Operation.GET_LOCAL,
                    expr_keys_local,
                    Operation.GET_LOCAL,
                    loop_index_local,
                    Operation.GET_PROPERTY,
                    Operation.SET_LOCAL,
                    key_var_local,
                ]
            )
        body.extend(
            [
                Operation.GET_LOCAL,
                expr_values_local,
                Operation.GET_LOCAL,
                loop_index_local,
                Operation.GET_PROPERTY,
                Operation.SET_LOCAL,
                value_var_local,
            ]
        )

        # the actual body
        body.extend(self.visit(node.body))

        # i += 1 at the end
        increment = [
            Operation.GET_LOCAL,
            loop_index_local,
            Operation.INTEGER,
            1,
            Operation.PLUS,
            Operation.SET_LOCAL,
            loop_index_local,
        ]

        # add to response
        response.extend(condition)
        response.extend([Operation.JUMP_IF_FALSE, len(body) + len(increment) + 2])
        response.extend(body)
        response.extend(increment)
        response.extend([Operation.JUMP, -len(increment) - len(body) - 2 - len(condition) - 2])

        response.extend(self._end_scope())
        return response

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        self._declare_local(node.name)
        if node.expr:
            return self.visit(node.expr)
        return [Operation.NULL]

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        if isinstance(node.left, ast.TupleAccess):
            return [
                *self.visit(node.left.tuple),
                Operation.INTEGER,
                node.left.index,
                *self.visit(node.right),
                Operation.SET_PROPERTY,
            ]

        if isinstance(node.left, ast.ArrayAccess):
            return [
                *self.visit(node.left.array),
                *self.visit(node.left.property),
                *self.visit(node.right),
                Operation.SET_PROPERTY,
            ]

        if isinstance(node.left, ast.Field) and len(node.left.chain) >= 1:
            ops: list
            chain = node.left.chain
            name = chain[0]
            for index, local in reversed(list(enumerate(self.locals))):
                if local.name == name:
                    # Set a local variable
                    if len(node.left.chain) == 1:
                        return [*self.visit(cast(AST, node.right)), Operation.SET_LOCAL, index]

                    # else set a property on a local object
                    ops = [Operation.GET_LOCAL, index]
                    for element in chain[1:-1]:
                        if isinstance(element, int):
                            ops.extend([Operation.INTEGER, element, Operation.GET_PROPERTY])
                        else:
                            ops.extend([Operation.STRING, str(element), Operation.GET_PROPERTY])
                    if isinstance(chain[-1], int):
                        ops.extend([Operation.INTEGER, chain[-1], *self.visit(node.right), Operation.SET_PROPERTY])
                    else:
                        ops.extend([Operation.STRING, str(chain[-1]), *self.visit(node.right), Operation.SET_PROPERTY])

                    return ops

            upvalue_index = self._resolve_upvalue(str(chain[0]))
            if upvalue_index != -1:
                # Set an upvalue
                if len(node.left.chain) == 1:
                    return [*self.visit(cast(AST, node.right)), Operation.SET_UPVALUE, upvalue_index]

                # else set a property on an upvalue object
                ops = [Operation.GET_UPVALUE, upvalue_index]
                for element in chain[1:-1]:
                    if isinstance(element, int):
                        ops.extend([Operation.INTEGER, element, Operation.GET_PROPERTY])
                    else:
                        ops.extend([Operation.STRING, str(element), Operation.GET_PROPERTY])
                if isinstance(chain[-1], int):
                    ops.extend([Operation.INTEGER, chain[-1], *self.visit(node.right), Operation.SET_PROPERTY])
                else:
                    ops.extend([Operation.STRING, str(chain[-1]), *self.visit(node.right), Operation.SET_PROPERTY])

                return ops
            raise QueryError(f'Variable "{name}" not declared in this scope. Can not assign to globals.')

        raise QueryError(f"Can not assign to this type of expression")

    def visit_function(self, node: ast.Function):
        # add an implicit return if none at the end of the function
        body = node.body

        # Sometimes blocks like `fn x() {foo}` get parsed as placeholders
        if isinstance(body, ast.Placeholder):
            body = ast.Block(declarations=[ast.ExprStatement(expr=body.expr), ast.ReturnStatement(expr=None)])
        elif isinstance(node.body, ast.Block):
            if len(node.body.declarations) == 0 or not isinstance(node.body.declarations[-1], ast.ReturnStatement):
                body = ast.Block(declarations=[*node.body.declarations, ast.ReturnStatement(expr=None)])
        elif not isinstance(node.body, ast.ReturnStatement):
            body = ast.Block(declarations=[node.body, ast.ReturnStatement(expr=None)])

        self._declare_local(node.name)
        compiler = BytecodeCompiler(self.supported_functions, node.params, self.context, self)
        bytecode = compiler.visit(body)

        ops = [
            Operation.CALLABLE,
            node.name,
            len(node.params),
            len(compiler.upvalues),
            len(bytecode),
            *bytecode,
            Operation.CLOSURE,
            len(compiler.upvalues),
        ]
        for upvalue in compiler.upvalues:
            ops.extend([upvalue.is_local, upvalue.index])
        return ops

    def visit_lambda(self, node: ast.Lambda):
        # add an implicit return if none at the end of the function
        expr: ast.Expr | ast.Statement = node.expr

        # Sometimes blocks like `x -> {foo}` get parsed as placeholders
        if isinstance(expr, ast.Placeholder):
            expr = ast.Block(declarations=[ast.ExprStatement(expr=expr.expr), ast.ReturnStatement(expr=None)])
        elif isinstance(expr, ast.Block):
            if len(expr.declarations) == 0 or not isinstance(expr.declarations[-1], ast.ReturnStatement):
                expr = ast.Block(declarations=[*expr.declarations, ast.ReturnStatement(expr=None)])
        elif not isinstance(expr, ast.ReturnStatement):
            if isinstance(expr, ast.Statement):
                expr = ast.Block(declarations=[expr, ast.ReturnStatement(expr=None)])
            else:
                expr = ast.ReturnStatement(expr=expr)

        compiler = BytecodeCompiler(self.supported_functions, node.args, self.context, self)
        bytecode = compiler.visit(expr)
        ops = [
            Operation.CALLABLE,
            "lambda",
            len(node.args),
            len(compiler.upvalues),
            len(bytecode),
            *bytecode,
            Operation.CLOSURE,
            len(compiler.upvalues),
        ]
        for upvalue in compiler.upvalues:
            ops.extend([upvalue.is_local, upvalue.index])
        return ops

    def visit_dict(self, node: ast.Dict):
        response = []
        for key, value in node.items:
            response.extend(self.visit(key))
            response.extend(self.visit(value))
        response.append(Operation.DICT)
        response.append(len(node.items))
        return response

    def visit_array(self, node: ast.Array):
        response = []
        for item in node.exprs:
            response.extend(self.visit(item))
        response.append(Operation.ARRAY)
        response.append(len(node.exprs))
        return response

    def visit_tuple(self, node: ast.Tuple):
        response = []
        for item in node.exprs:
            response.extend(self.visit(item))
        response.append(Operation.TUPLE)
        response.append(len(node.exprs))
        return response

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        response = []
        tag_name = node.kind
        tag_is_callable = (
            any(local for local in self.locals if local.name == node.kind) or self._resolve_upvalue(tag_name) != -1
        )
        if tag_is_callable:
            # first the dict as an attribute
            for attribute in node.attributes:
                response.extend(self._visit_hogqlx_value(attribute.name))
                response.extend(self._visit_hogqlx_value(attribute.value))
            response.append(Operation.DICT)
            response.append(len(node.attributes))
            # then the call itself
            response.extend(self.visit_field(ast.Field(chain=[tag_name])))
            response.extend([Operation.CALL_LOCAL, 1])
        else:
            # first the __hx_tag marker
            response.extend(self._visit_hogqlx_value("__hx_tag"))
            response.extend(self._visit_hogqlx_value(node.kind))
            # then the rest of the attributes
            for attribute in node.attributes:
                response.extend(self._visit_hogqlx_value(attribute.name))
                response.extend(self._visit_hogqlx_value(attribute.value))
            response.append(Operation.DICT)
            response.append(len(node.attributes) + 1)
        return response

    def _visit_hog_ast(self, node: ast.AST | None):
        if node is None:
            return [Operation.NULL]
        if isinstance(node, ast.HogQLXTag):
            tag_name = node.kind
            tag_is_callable = (
                any(local for local in self.locals if local.name == node.kind) or self._resolve_upvalue(tag_name) != -1
            )
            if tag_is_callable:
                return self.visit_hogqlx_tag(node)
        response = []
        # We consider any object with the element "__hx_ast" to be a HogQLX AST node
        response.extend([Operation.STRING, "__hx_ast"])
        response.extend([Operation.STRING, node.__class__.__name__])
        fields = 1
        for field in dataclasses.fields(node):
            if field.name in ["start", "end", "type"]:
                continue
            value = getattr(node, field.name)
            if value is None:
                continue
            response.extend([Operation.STRING, field.name])
            response.extend(self._visit_hogqlx_value(value))
            fields += 1
        response.append(Operation.DICT)
        response.append(fields)
        return response

    def _visit_hogqlx_value(self, value: Any) -> list[Any]:
        if isinstance(value, AST):
            return self.visit(value)
        if isinstance(value, list):
            elems = []
            for v in value:
                elems.extend(self._visit_hogqlx_value(v))
            return [*elems, Operation.ARRAY, len(value)]
        if isinstance(value, dict):
            elems = []
            for k, v in value.items():
                elems.extend(self._visit_hogqlx_value(k))
                elems.extend(self._visit_hogqlx_value(v))
            return [*elems, Operation.DICT, len(value.items())]
        if isinstance(value, ast.AST):
            if isinstance(value, ast.Placeholder):
                if self.mode == "hog":
                    raise QueryError("Placeholders are not allowed in this context")
                prev_mode = self.mode
                self.mode = "hog"
                try:
                    response = self.visit(value.expr)
                finally:
                    self.mode = prev_mode
                return response
            return self._visit_hog_ast(value)
        if isinstance(value, StrEnum):
            return [Operation.STRING, value.value]
        if isinstance(value, int):
            return [Operation.INTEGER, value]
        if isinstance(value, float):
            return [Operation.FLOAT, value]
        if isinstance(value, str):
            return [Operation.STRING, value]
        if value is True:
            return [Operation.TRUE]
        if value is False:
            return [Operation.FALSE]
        return [Operation.NULL]

    def visit_placeholder(self, node: ast.Placeholder):
        if self.mode == "ast":
            self.mode = "hog"
            try:
                result = self.visit(node.expr)
            finally:
                self.mode = "ast"
            return result
        raise QueryError("Placeholders are not allowed in this context")

    def visit_select_query(self, node: ast.SelectQuery):
        # Select queries always takes us into "ast" mode
        prev_mode = self.mode
        self.mode = "ast"
        try:
            response = self._visit_hog_ast(node)
        finally:
            self.mode = prev_mode
        return response

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        # Select queries always takes us into "ast" mode
        prev_mode = self.mode
        self.mode = "ast"
        try:
            response = self._visit_hog_ast(node)
        finally:
            self.mode = prev_mode
        return response


def execute_hog(
    source_code: str,
    team: Optional["Team"] = None,
    globals: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Callable[..., Any]]] = None,
    timeout=timedelta(seconds=10),
) -> BytecodeResult:
    source_code = source_code.strip()
    if source_code.count("\n") == 0:
        if not source_code.startswith("return") and ":=" not in source_code:
            source_code = f"return {source_code}"
        if not source_code.endswith(";"):
            source_code = f"{source_code};"
    program = parse_program(source_code)
    bytecode = create_bytecode(
        program,
        supported_functions=set(functions.keys()) if functions is not None else set(),
        context=HogQLContext(team_id=team.id if team else None),
    ).bytecode
    return execute_bytecode(bytecode, globals=globals, functions=functions, timeout=timeout, team=team)
