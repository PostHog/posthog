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


def rewrite_json_extract_to_property(node, context: HogQLContext):
    """
    Rewrite `JSONExtractString(<lazy-table JSON field>, '<constant key>')` into the equivalent HogQL
    property access (`<field>.<key>`).

    The argMax-based lazy tables (`groups`, `persons`) aggregate each requested field, so accessing a
    property via dot syntax projects only that single field into the argMax. An explicit
    `JSONExtractString(properties, 'name')` instead requests the whole `properties` field, so the
    argMax materializes the entire JSON blob per group/person, which can exhaust memory. Converting it
    to a property access lets the existing projection-into-argMax path apply.

    Emits untyped property-access nodes; the caller re-runs type resolution so the resolver assigns
    types, rather than constructing them here.
    """
    return _Transformer(context).visit(node)


class _Finder(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.found = False

    def visit_call(self, node: ast.Call):
        if _matched_property_access(node, self.context) is not None:
            self.found = True
        super().visit_call(node)


class _Transformer(CloningVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__(clear_types=True)
        self.context = context

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None:
            chain, key = matched
            return ast.Field(chain=[*chain, key])
        return super().visit_call(node)
