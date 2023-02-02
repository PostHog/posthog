from typing import Any, Dict, List, cast

from posthog.hogql import ast


def replace_placeholders_list(node: List[ast.Expr], placeholders: Dict[str, ast.Expr]) -> List[ast.Expr]:
    # TODO: type generics?
    if node is None:
        return cast(Any, node)
    return [replace_placeholders(child, placeholders) for child in node]


def replace_placeholders(node: ast.Expr, placeholders: Dict[str, ast.Expr]) -> ast.Expr:
    # TODO: convert to a visitor pattern
    if isinstance(node, ast.Placeholder):
        if node.field in placeholders:
            return placeholders[node.field]
        raise ValueError(f"Placeholder '{node.field}' not found in provided dict: {', '.join(list(placeholders))}")
    elif isinstance(node, ast.BinaryOperation):
        return ast.BinaryOperation(
            left=replace_placeholders(node.left, placeholders),
            right=replace_placeholders(node.right, placeholders),
            op=node.op,
        )
    elif isinstance(node, ast.CompareOperation):
        return ast.CompareOperation(
            left=replace_placeholders(node.left, placeholders),
            right=replace_placeholders(node.right, placeholders),
            op=node.op,
        )
    elif isinstance(node, ast.And):
        return ast.And(exprs=replace_placeholders_list(node.exprs, placeholders))
    elif isinstance(node, ast.Or):
        return ast.Or(exprs=replace_placeholders_list(node.exprs, placeholders))
    elif isinstance(node, ast.Not):
        return ast.Not(expr=replace_placeholders(node.expr, placeholders))
    elif isinstance(node, ast.OrderExpr):
        return ast.OrderExpr(expr=replace_placeholders(node.expr, placeholders), order=node.order)
    elif isinstance(node, ast.Call):
        return ast.Call(name=node.name, args=replace_placeholders_list(node.args, placeholders))
    elif isinstance(node, ast.JoinExpr):
        return ast.JoinExpr(
            table=cast(Any, replace_placeholders(node.table, placeholders)),
            join_expr=cast(Any, replace_placeholders(node.join_expr, placeholders)),
            table_final=node.table_final,
            alias=node.alias,
            join_type=node.join_type,
            join_constraint=node.join_constraint,
        )
    elif isinstance(node, ast.SelectQuery):
        return ast.SelectQuery(
            select=replace_placeholders_list(node.select, placeholders),
            select_from=cast(ast.JoinExpr, replace_placeholders(node.select_from, placeholders)),
            where=replace_placeholders(node.where, placeholders),
            prewhere=replace_placeholders(node.prewhere, placeholders),
            having=replace_placeholders(node.having, placeholders),
            group_by=replace_placeholders_list(node.group_by, placeholders),
            limit=node.limit,
            offset=node.offset,
        )
    elif isinstance(node, ast.Constant) or isinstance(node, ast.FieldAccess) or isinstance(node, ast.FieldAccessChain):
        pass
    elif isinstance(node, ast.Expr):
        raise NotImplementedError(f"replace_placeholders not implemented for {type(node).__name__}")

    return node
