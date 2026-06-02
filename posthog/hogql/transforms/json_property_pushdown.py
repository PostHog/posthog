from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.visitor import CloningVisitor

# JSON-string extraction calls that are equivalent to a HogQL string property access.
# Other JSONExtract* variants (Int/Float/Bool/Raw) return non-string types, so the property-access
# rewrite would change the result type; those are intentionally left untouched.
STRING_EXTRACT_FUNCTIONS = {"JSONExtractString"}


def pushdown_json_extract_to_property(node, context: HogQLContext):
    """
    Rewrite `JSONExtractString(<lazy-table JSON field>, '<constant key>')` into the equivalent HogQL
    property access (`<field>.<key>`).

    The argMax-based lazy tables (`groups`, `persons`) aggregate each requested field, so accessing a
    property via dot syntax projects only that single field into the argMax. An explicit
    `JSONExtractString(properties, 'name')` instead requests the whole `properties` field, so the
    argMax materializes the entire JSON blob per group/person, which can exhaust memory. Converting it
    to a property access lets the existing projection-into-argMax path apply.

    Restricted to lazy tables so non-aggregated tables (e.g. events) are unaffected. Runs after type
    resolution and before lazy-table resolution; it produces a fully typed property-access node, so no
    re-resolution is needed.
    """
    return _JSONExtractToPropertyTransformer(context).visit(node)


class _JSONExtractToPropertyTransformer(CloningVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__(clear_types=False)
        self.context = context

    def visit_call(self, node: ast.Call):
        node = super().visit_call(node)  # clone and recurse into arguments first
        rewritten = self._rewrite(node)
        return rewritten if rewritten is not None else node

    def _rewrite(self, node: ast.Call):
        if node.name not in STRING_EXTRACT_FUNCTIONS or len(node.args) != 2:
            return None

        field_arg, key = node.args
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None

        # The column reference may be wrapped in a field alias by the resolver; unwrap to the Field
        # and its FieldType.
        inner = field_arg.expr if isinstance(field_arg, ast.Alias) else field_arg
        if not isinstance(inner, ast.Field):
            return None
        field_type = field_arg.type
        if isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if not isinstance(field_type, ast.FieldType):
            return None

        # Only rewrite for the argMax-based lazy tables, where projecting the property into the
        # aggregate is the win. Unwrap aliases/virtual tables to find the underlying table type.
        table_type = field_type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, (ast.LazyTableType, ast.LazyJoinType)):
            return None

        if not isinstance(field_type.resolve_database_field(self.context), StringJSONDatabaseField):
            return None

        # Build the typed property access, mirroring what the resolver produces for `field.key`.
        property_type = field_type.get_child(key.value, self.context)
        return ast.Field(chain=[*inner.chain, key.value], type=property_type)
