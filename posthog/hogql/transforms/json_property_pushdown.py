from typing import TypeVar, cast

from django.db import models
from django.db.models.functions.comparison import Coalesce

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.models import PropertyDefinition, Team

_T_AST = TypeVar("_T_AST", bound=ast.AST)

# JSON-string extraction calls that are equivalent to a HogQL string property access.
# Other JSONExtract* variants (Int/Float/Bool/Raw) return non-string types, so the property-access
# rewrite would change the result type; those are intentionally left untouched.
STRING_EXTRACT_FUNCTIONS = {"JSONExtractString"}

# PropertyDefinition types that PropertySwapper rewrites a property access into a non-String expression
# (Numeric -> toFloat, Boolean -> toBool, DateTime -> toDateTime). Wrapping one of those in `ifNull(..., '')`
# has no common ClickHouse supertype with the '' String, so a JSONExtractString on such a property must NOT
# be rewritten; it is left as-is (JSONExtractString already returns a non-nullable String).
SWAP_TYPED_PROPERTY_TYPES = {"Numeric", "Boolean", "DateTime"}

# (definition type, group type index, property name) -> whether the property is swap-typed.
_SwapTypedCache = dict[tuple[int, int | None, str], bool]


def _matched_property_access(node: ast.AST, context: HogQLContext):
    """If `node` is `JSONExtractString(<lazy-table JSON field>, '<constant key>')`, return
    (field_chain, key, table_type) so it can be rewritten to a property access. Otherwise return None."""
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

    return inner.chain, key.value, table_type


def rewrite_json_extract_to_property(node: _T_AST, context: HogQLContext) -> tuple[_T_AST, bool]:
    """
    Rewrite `JSONExtractString(<lazy-table JSON field>, '<constant key>')` into `ifNull(<field>.<key>, '')`.

    The argMax-based lazy tables (`groups`, `persons`) aggregate each requested field, so accessing a
    property via dot syntax projects only that single field into the argMax, whereas an explicit
    `JSONExtractString(properties, 'name')` requests the whole `properties` field and makes the argMax
    materialize the entire JSON blob per group/person, which can exhaust memory.

    Only String/untyped properties are rewritten. A Numeric/Boolean/DateTime-typed property is type-swapped
    by PropertySwapper to a non-String expression, and `ifNull(<non-string>, '')` has no common ClickHouse
    supertype with the '' default (a NO_COMMON_TYPE error). Those are left as the original JSONExtractString,
    which already returns a String.

    Property access returns NULL for a missing key while `JSONExtractString` returns ''; the `ifNull(..., '')`
    wrapper restores that, so the rewrite matches `JSONExtractString` for scalar values and missing keys and
    keeps the non-nullable String type.

    Returns (node, rewritten). When nothing is rewritten the original node is returned unchanged, so the
    caller can skip the (otherwise wasted) re-resolution. Emits untyped nodes; the caller re-runs type
    resolution to assign types.
    """
    cache: _SwapTypedCache = {}
    finder = _Finder(context, cache)
    finder.visit(node)
    if not finder.found:
        return node, False
    return cast(_T_AST, _Transformer(context, cache).visit(node)), True


def _is_swap_typed(
    context: HogQLContext,
    table_type: ast.LazyTableType | ast.LazyJoinType,
    property_name: str,
    cache: _SwapTypedCache,
) -> bool:
    """True if `property_name` on this persons/groups table has a Numeric/Boolean/DateTime PropertyDefinition.
    PropertySwapper rewrites such a property access to a non-String expression, which ifNull(..., '') cannot
    wrap, so the JSONExtractString rewrite must be skipped for it."""
    if not context.team_id:
        return False
    team = context.team or Team.objects.filter(id=context.team_id).first()
    if team is None:
        return False
    context.team = team

    resolved_table = table_type.resolve_database_table(context)
    if isinstance(resolved_table, (PersonsTable, RawPersonsTable)):
        definition_type = PropertyDefinition.Type.PERSON
        group_type_index = None
    elif isinstance(resolved_table, GroupsTable):
        definition_type = PropertyDefinition.Type.GROUP
        group_type_index = _group_type_index(context, table_type)
    else:
        return False

    cache_key = (int(definition_type), group_type_index, property_name)
    if cache_key in cache:
        return cache[cache_key]

    query = PropertyDefinition.objects.alias(
        effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
    ).filter(
        effective_project_id=team.project_id,
        name=property_name,
        type=definition_type,
        property_type__in=SWAP_TYPED_PROPERTY_TYPES,
    )
    # When the group type index is unknown (e.g. `FROM groups` without a group_id), match any group type for
    # the name: if any is non-String, skip the rewrite to stay safe.
    if group_type_index is not None:
        query = query.filter(group_type_index=group_type_index)

    result = query.exists()
    cache[cache_key] = result
    return result


def _group_type_index(context: HogQLContext, table_type: ast.LazyTableType | ast.LazyJoinType) -> int | None:
    if isinstance(table_type, ast.LazyJoinType) and table_type.field.startswith("group_"):
        return int(table_type.field.split("_")[1])
    if isinstance(table_type, ast.LazyTableType) and context.globals:
        group_id = context.globals.get("group_id")
        if isinstance(group_id, int):
            return group_id
    return None


class _Finder(TraversingVisitor):
    def __init__(self, context: HogQLContext, cache: _SwapTypedCache):
        super().__init__()
        self.context = context
        self.cache = cache
        self.found = False

    def visit(self, node: ast.AST | None):
        if not self.found:
            super().visit(node)

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None:
            _chain, key, table_type = matched
            # Only a rewritable (String/untyped) match counts. Skipping swap-typed matches here keeps the
            # caller from running the rewrite + re-resolution for queries where nothing would be rewritten.
            if not _is_swap_typed(self.context, table_type, key, self.cache):
                self.found = True
                return
        super().visit_call(node)


class _Transformer(CloningVisitor):
    def __init__(self, context: HogQLContext, cache: _SwapTypedCache):
        super().__init__(clear_types=True)
        self.context = context
        self.cache = cache

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None:
            chain, key, table_type = matched
            if not _is_swap_typed(self.context, table_type, key, self.cache):
                # JSONExtractString returns '' for a missing key; property access returns NULL. Wrap in
                # ifNull(..., '') to keep that contract and the non-nullable String type.
                return ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=[*chain, key]), ast.Constant(value="")],
                )
        return super().visit_call(node)
