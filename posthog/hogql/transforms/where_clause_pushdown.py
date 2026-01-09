from typing import Optional

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class FieldReferenceRewriter(CloningVisitor):
    def __init__(self, outer_table_alias: str, inner_table_name: str):
        super().__init__(clear_locations=True)
        self.outer_table_alias = outer_table_alias
        self.inner_table_name = inner_table_name

    def visit_field(self, node: ast.Field):
        if len(node.chain) >= 2 and node.chain[0] == self.outer_table_alias:
            return ast.Field(chain=[self.inner_table_name, *node.chain[1:]])
        elif len(node.chain) == 1:
            return ast.Field(chain=[self.inner_table_name, node.chain[0]])
        return ast.Field(chain=list(node.chain))


def get_inner_field_names(inner_query: ast.SelectQuery) -> set[str]:
    field_names: set[str] = set()
    if not inner_query.select:
        return field_names

    for expr in inner_query.select:
        if isinstance(expr, ast.Alias):
            if not isinstance(expr.expr, ast.Constant):
                field_names.add(expr.alias)
        elif isinstance(expr, ast.Field) and expr.chain:
            field_names.add(str(expr.chain[-1]))

    return field_names


def get_field_name_from_expr(expr: ast.Expr, outer_table_alias: str) -> Optional[str]:
    if isinstance(expr, ast.Alias):
        expr = expr.expr

    if isinstance(expr, ast.Field) and expr.chain:
        if len(expr.chain) == 1:
            return str(expr.chain[0])
        elif len(expr.chain) >= 2 and expr.chain[0] == outer_table_alias:
            return str(expr.chain[1])

    return None


def is_pushdown_candidate(
    expr: ast.Expr,
    inner_field_names: set[str],
    outer_table_alias: str,
) -> bool:
    if isinstance(expr, ast.CompareOperation):
        left_field = get_field_name_from_expr(expr.left, outer_table_alias)
        right_field = get_field_name_from_expr(expr.right, outer_table_alias)

        if left_field and left_field in inner_field_names:
            return True
        if right_field and right_field in inner_field_names:
            return True

    return False


def extract_pushdown_candidates(
    where: ast.Expr,
    inner_field_names: set[str],
    outer_table_alias: str,
) -> tuple[list[ast.Expr], list[ast.Expr]]:
    candidates: list[ast.Expr] = []
    remaining: list[ast.Expr] = []

    if isinstance(where, ast.And):
        for expr in where.exprs:
            if is_pushdown_candidate(expr, inner_field_names, outer_table_alias):
                candidates.append(expr)
            else:
                remaining.append(expr)
    else:
        if is_pushdown_candidate(where, inner_field_names, outer_table_alias):
            candidates.append(where)
        else:
            remaining.append(where)

    return candidates, remaining


def combine_where_clauses(existing: Optional[ast.Expr], new_clauses: list[ast.Expr]) -> Optional[ast.Expr]:
    if not new_clauses:
        return existing

    all_clauses: list[ast.Expr] = []

    if existing:
        if isinstance(existing, ast.And):
            all_clauses.extend(existing.exprs)
        else:
            all_clauses.append(existing)

    all_clauses.extend(new_clauses)

    if len(all_clauses) == 1:
        return all_clauses[0]

    return ast.And(exprs=all_clauses)


def push_down_where_clauses(
    outer_query: ast.SelectQuery,
    inner_query: ast.SelectQuery,
    outer_table_alias: str,
    inner_table_name: str,
) -> None:
    if not outer_query or not outer_query.where:
        return

    inner_field_names = get_inner_field_names(inner_query)
    if not inner_field_names:
        return

    candidates, _remaining = extract_pushdown_candidates(
        outer_query.where,
        inner_field_names,
        outer_table_alias,
    )

    if not candidates:
        return

    rewriter = FieldReferenceRewriter(outer_table_alias, inner_table_name)
    rewritten_candidates = [rewriter.visit(c) for c in candidates]

    inner_query.where = combine_where_clauses(inner_query.where, rewritten_candidates)
