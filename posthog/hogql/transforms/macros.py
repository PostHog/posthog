from typing import List, Optional, Dict

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
        self.macro_scopes: List[Optional[Dict[str, ast.Macro]]] = scopes or []

    def visit_select_query(self, node: ast.SelectQuery):
        self.macro_scopes.append(node.macros)
        response = super().visit_select_query(node)
        response.macros = None
        self.macro_scopes.pop()
        return response

    def visit_field(self, node: ast.Field):
        if len(self.macro_scopes) > 0 and len(node.chain) == 1:
            for macro_scope in reversed(self.macro_scopes):
                if macro_scope and node.chain[0] in macro_scope:
                    macro = macro_scope[node.chain[0]]
                    if macro.macro_format == "subquery":
                        return ast.Field(chain=[node.chain[0]])
                    return self.visit(clone_expr(macro.expr))
        return node

    def visit_join_expr(self, node: ast.JoinExpr):
        node = super().visit_join_expr(node)
        if len(self.macro_scopes) > 0 and isinstance(node.table, ast.Field):
            for macro_scope in reversed(self.macro_scopes):
                if macro_scope and len(node.table.chain) == 1 and node.table.chain[0] in macro_scope:
                    node.alias = node.table.chain[0]
                    node.table = clone_expr(macro_scope[node.table.chain[0]].expr)
                    node.table = self.visit(node.table)
        if node.next_join:
            self.visit(node.next_join)
        return node
