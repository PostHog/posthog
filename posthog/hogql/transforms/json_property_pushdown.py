from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

# JSON-string extraction calls that are equivalent to a HogQL string property access.
# Other JSONExtract* variants (Int/Float/Bool/Raw) return non-string types, so the property-access
# rewrite would change the result type; those are intentionally left untouched.
STRING_EXTRACT_FUNCTIONS = {"JSONExtractString"}


def _matched_property_access(node: ast.AST, context: HogQLContext):
    """If `node` is `JSONExtractString(<lazy-table JSON field>, '<constant key>')`, return
    (field_chain, key) so it can be rewritten to a property access. Otherwise return None."""
    if not isinstance(node, ast.Call) or node.name not in STRING_EXTRACT_FUNCTIONS or len(node.args) != 2:
        return None

    field_arg, key = node.args
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
        return None

    # The column reference may be wrapped in a field alias by the resolver; unwrap to the Field.
    inner = field_arg.expr if isinstance(field_arg, ast.Alias) else field_arg
    if not isinstance(inner, ast.Field):
        return None
    field_type = field_arg.type
    if isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType):
        return None

    # Only the argMax-based lazy tables (groups/persons) benefit, since they aggregate each
    # requested field. Unwrap aliases/virtual tables to find the underlying table type.
    table_type = field_type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        table_type = table_type.table_type
    if not isinstance(table_type, (ast.LazyTableType, ast.LazyJoinType)):
        return None

    if not isinstance(field_type.resolve_database_field(context), StringJSONDatabaseField):
        return None

    return inner.chain, key.value


def has_rewritable_json_extract(node: ast.AST, context: HogQLContext) -> bool:
    finder = _Finder(context)
    finder.visit(node)
    return finder.found


def rewrite_json_extract_to_property(node: ast.AST, context: HogQLContext):
    """
    Rewrite `JSONExtractString(<lazy-table JSON field>, '<constant key>')` into
    `ifNull(<field>.<key>, '')`.

    The argMax-based lazy tables (`groups`, `persons`) aggregate each requested field, so accessing a
    property via dot syntax projects only that single field into the argMax, whereas an explicit
    `JSONExtractString(properties, 'name')` requests the whole `properties` field and makes the argMax
    materialize the entire JSON blob per group/person, which can exhaust memory.

    Property access returns NULL for a missing key while `JSONExtractString` returns ''; the
    `ifNull(..., '')` wrapper restores that, so the rewrite matches `JSONExtractString` for scalar
    values and missing keys and keeps the non-nullable String type.

    Emits untyped nodes; the caller re-runs type resolution to assign types.
    """
    return _Transformer(context).visit(node)


class _Finder(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.found = False

    def visit(self, node: ast.AST | None):
        if not self.found:
            super().visit(node)

    def visit_call(self, node: ast.Call):
        if _matched_property_access(node, self.context) is not None:
            self.found = True
            return
        super().visit_call(node)


class _Transformer(CloningVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__(clear_types=True)
        self.context = context

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None:
            chain, key = matched
            # JSONExtractString returns '' for a missing key; property access returns NULL. Wrap in
            # ifNull(..., '') to keep that contract and the non-nullable String type.
            return ast.Call(
                name="ifNull",
                args=[ast.Field(chain=[*chain, key]), ast.Constant(value="")],
            )
        return super().visit_call(node)
