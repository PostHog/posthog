from typing import Literal

from posthog.hogql import ast
from posthog.hogql.ast import AST
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ImpossibleASTError, QueryError
from posthog.hogql.escape_sql import escape_postgres_identifier
from posthog.hogql.printer import HogQLPrinter


class PostgresPrinter(HogQLPrinter):
    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["postgres"],
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty)

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(map(str, node.chain))}")

        return self.visit(node.type)

    def visit_call(self, node: ast.Call):
        # No function call validation for postgres
        args = [self.visit(arg) for arg in node.args]

        if node.name.lower() in ["and", "or"]:
            if len(args) == 0:
                return f"{node.name}()"
            if len(args) == 1:
                return args[0]

            operator = "AND" if node.name.lower() == "and" else "OR"
            joined_args = f" {operator} ".join(args)
            return f"({joined_args})"

        return f"{node.name}({', '.join(args)})"

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_postgres()

    def _visit_in_values(self, node: ast.Expr) -> str:
        if isinstance(node, ast.Tuple):
            return f"({', '.join(self.visit(value) for value in node.exprs)})"
        elif isinstance(node, ast.Constant):
            return f"({self.visit(node)})"

        return self.visit(node)

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)

        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            right = self._visit_in_values(node.right)
        else:
            right = self.visit(node.right)

        return self._get_compare_op(node.op, left, right)

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Eq:
            return f"({left} = {right})"
        elif op == ast.CompareOperationOp.NotEq:
            return f"({left} != {right})"
        elif op == ast.CompareOperationOp.Like:
            return f"({left} LIKE {right})"
        elif op == ast.CompareOperationOp.NotLike:
            return f"({left} NOT LIKE {right})"
        elif op == ast.CompareOperationOp.ILike:
            return f"({left} ILIKE {right})"
        elif op == ast.CompareOperationOp.NotILike:
            return f"({left} NOT ILIKE {right})"
        elif op == ast.CompareOperationOp.In:
            return f"({left} IN {right})"
        elif op == ast.CompareOperationOp.NotIn:
            return f"({left} NOT IN {right})"
        elif op == ast.CompareOperationOp.Regex:
            return f"({left} ~ {right})"
        elif op == ast.CompareOperationOp.NotRegex:
            return f"({left} !~ {right})"
        elif op == ast.CompareOperationOp.IRegex:
            return f"({left} ~* {right})"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f"({left} !~* {right})"
        elif op == ast.CompareOperationOp.Gt:
            return f"({left} > {right})"
        elif op == ast.CompareOperationOp.GtEq:
            return f"({left} >= {right})"
        elif op == ast.CompareOperationOp.Lt:
            return f"({left} < {right})"
        elif op == ast.CompareOperationOp.LtEq:
            return f"({left} <= {right})"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {op.name}")

    def _print_table_ref(self, table_type: ast.TableType, node: ast.JoinExpr) -> str:
        return table_type.table.to_printed_postgres()

    def _ensure_team_id_where_clause(self, table_type: ast.TableType, node_type: ast.TableOrSelectType): ...

    def _print_identifier(self, name: str) -> str:
        return escape_postgres_identifier(name)

    def _json_property_args(self, chain):
        return [self._print_escaped_string(name) for name in chain]
