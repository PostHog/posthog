from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor, clone_expr

MAX_RECURSION_DEPTH = 50


def expand_macros(node: ast.Expr, scopes: Optional[List[ast.SelectQuery]] = None, depth=0):
    if depth > MAX_RECURSION_DEPTH:
        raise Exception(
            f"Expanded macros over {MAX_RECURSION_DEPTH} levels deep. Likely an infinite loop at this point."
        )
    return MacroExpander(scopes=scopes, depth=depth).visit(node)


class MacroExpander(CloningVisitor):
    def __init__(self, depth: int, scopes: Optional[List[ast.SelectQuery]] = None):
        super().__init__()
        self.depth = depth
        self.scopes: List[ast.SelectQuery] = scopes or []

    def visit_select_query(self, node: ast.SelectQuery):
        self.scopes.append(node)
        response = super().visit_select_query(node)
        response.macros = None
        self.scopes.pop()
        return response

    def visit_field(self, node: ast.Field):
        if len(self.scopes) > 0 and len(node.chain) == 1:
            for scope in reversed(self.scopes):
                if scope.macros and node.chain[0] in scope.macros:
                    macro = scope.macros[node.chain[0]]
                    if macro.macro_format == "subquery":
                        return ast.Field(chain=[node.chain[0]])
                    return self.visit(clone_expr(macro.expr))
        return node

    def visit_join_expr(self, node: ast.JoinExpr):
        node = super().visit_join_expr(node)
        if len(self.scopes) > 0 and isinstance(node.table, ast.Field):
            for scope in reversed(self.scopes):
                if scope.macros and len(node.table.chain) == 1 and node.table.chain[0] in scope.macros:
                    node.alias = node.table.chain[0]
                    node.table = self.visit(clone_expr(scope.macros[node.table.chain[0]].expr))
        if node.next_join:
            self.visit(node.next_join)
        return node
