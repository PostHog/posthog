from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class _ExpressionIdentity(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=True, clear_locations=True)

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)

    def visit_constant(self, node: ast.Constant) -> ast.Constant:
        constant = super().visit_constant(node)
        # Python considers 1, True, and 1.0 equal, but SQL casts distinguish their literal types.
        constant.value = (type(node.value), node.value)
        return constant

    def visit_field(self, node: ast.Field) -> ast.Field:
        field_type = node.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if isinstance(field_type, ast.PropertyType):
            return ast.Field(
                chain=[id(field_type.field_type.table_type), field_type.field_type.name, *field_type.chain]
            )
        if isinstance(field_type, ast.FieldType):
            # A resolved binding distinguishes joined columns even when their names match.
            return ast.Field(chain=[id(field_type.table_type), field_type.name])
        return super().visit_field(node)


def expression_identity(node: ast.Expr) -> ast.Expr:
    return _ExpressionIdentity().visit(node)


def positional_index(node: ast.Expr) -> int | None:
    if isinstance(node, ast.PositionalRef):
        return node.index
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None
