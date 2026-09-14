from dataclasses import fields

from posthog.hogql import ast


def expression_key(value: object) -> tuple[object, ...]:
    if isinstance(value, ast.Alias):
        return expression_key(value.expr)
    if isinstance(value, ast.Field):
        field_type = value.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if isinstance(field_type, ast.PropertyType):
            return (ast.Field, id(field_type.field_type.table_type), field_type.field_type.name, *field_type.chain)
        if isinstance(field_type, ast.FieldType):
            # A resolved binding distinguishes joined columns even when their names match.
            return (ast.Field, id(field_type.table_type), field_type.name)
    if isinstance(value, ast.AST):
        return (
            type(value),
            tuple(
                (field.name, expression_key(getattr(value, field.name)))
                for field in fields(value)
                if field.name not in {"start", "end", "type"}
            ),
        )
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(expression_key(item) for item in value))
    if isinstance(value, dict):
        return (dict, {key: expression_key(item) for key, item in value.items()})
    # Python considers 1, True, and 1.0 equal, but SQL casts distinguish their literal types.
    return (type(value), value)


def positional_index(node: ast.Expr) -> int | None:
    if isinstance(node, ast.PositionalRef):
        return node.index
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    return None
