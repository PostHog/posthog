from typing import Dict, List, Optional, overload

from posthog.hogql import ast


@overload
def replace_placeholders_list(node: None, placeholders: Dict[str, ast.Expr]) -> None:
    ...


@overload
def replace_placeholders_list(node: List[ast.Expr], placeholders: Dict[str, ast.Expr]) -> List[ast.Expr]:
    ...


def replace_placeholders_list(
    node: Optional[List[ast.Expr]], placeholders: Dict[str, ast.Expr]
) -> Optional[List[ast.Expr]]:
    if node is None:
        return None
    return [replace_placeholders(child, placeholders) for child in node]


def replace_placeholders(node: ast.Expr, placeholders: Dict[str, ast.Expr]) -> ast.Expr:
    # NOTE: Add new node types and fields here as they are added to the AST.
    # TODO: Convert to a true visitor pattern, possibly via Pydantic introspection
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
    elif isinstance(node, ast.Constant) or isinstance(node, ast.Field):
        pass
    elif isinstance(node, ast.Expr):
        raise NotImplementedError(f"replace_placeholders not implemented for {type(node).__name__}")

    return node
