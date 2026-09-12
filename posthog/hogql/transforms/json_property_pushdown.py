from typing import Literal, TypeVar, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.property_metadata import PropertyMetadata, load_property_metadata
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.dataclasses import frozen

_T_AST = TypeVar("_T_AST", bound=ast.AST)

# JSON-string extraction calls that are equivalent to a HogQL string property access.
# Other JSONExtract* variants (Int/Float/Bool/Raw) return non-string types, so the property-access
# rewrite would change the result type; those are intentionally left untouched.
STRING_EXTRACT_FUNCTIONS = {"JSONExtractString"}

# PropertySwapper turns a property access with one of these definition types into a non-String expression
# (toFloat / toBool / toDateTime), and ClickHouse has no supertype for `ifNull(<non-String>, '')`.
SWAP_TYPED_PROPERTY_TYPES = {"Numeric", "Boolean", "DateTime"}

# Where PropertySwapper buckets a lazy-table property: ("person", None) or ("group", group_type_index).
# None where it never retypes the property, such as `FROM groups` without a `group_id` global.
_SwapperBucket = tuple[Literal["person", "group"], int | None] | None


@frozen
class _PropertyExtract:
    """A `JSONExtractString(<lazy-table JSON field>, '<constant key>')` call: the JSON field's chain, the key,
    and where PropertySwapper would look the property up."""

    chain: tuple[str | int, ...]
    key: str
    bucket: _SwapperBucket


def _matched_property_access(node: ast.AST, context: HogQLContext) -> _PropertyExtract | None:
    """The `_PropertyExtract` for `node` when it is a rewritable JSONExtractString call, otherwise None."""
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

    return _PropertyExtract(chain=tuple(inner.chain), key=key.value, bucket=_swapper_bucket(table_type, context))


def _swapper_bucket(table_type: ast.LazyTableType | ast.LazyJoinType, context: HogQLContext) -> _SwapperBucket:
    """Mirrors PropertySwapper.visit_field, so the rewrite skips exactly the properties the swapper retypes."""
    resolved_table = table_type.resolve_database_table(context)
    if isinstance(resolved_table, (PersonsTable, RawPersonsTable)):
        return ("person", None)
    if not isinstance(resolved_table, GroupsTable):
        return None
    if isinstance(table_type, ast.LazyJoinType):
        return ("group", int(table_type.field.split("_")[1])) if table_type.field.startswith("group_") else None
    group_id = context.globals.get("group_id") if context.globals else None
    return ("group", group_id) if isinstance(group_id, int) else None


def rewrite_json_extract_to_property(node: _T_AST, context: HogQLContext) -> tuple[_T_AST, bool]:
    """
    Rewrite `JSONExtractString(<lazy-table JSON field>, '<constant key>')` into `ifNull(<field>.<key>, '')`.

    The argMax-based lazy tables (`groups`, `persons`) aggregate each requested field, so accessing a
    property via dot syntax projects only that single field into the argMax, whereas an explicit
    `JSONExtractString(properties, 'name')` requests the whole `properties` field and makes the argMax
    materialize the entire JSON blob per group/person, which can exhaust memory.

    Property access returns NULL for a missing key while `JSONExtractString` returns ''; the `ifNull(..., '')`
    wrapper restores that, so the rewrite matches `JSONExtractString` for scalar values and missing keys and
    keeps the non-nullable String type.

    A property that PropertySwapper retypes (a Numeric/Boolean/DateTime definition) keeps its
    `JSONExtractString`, because `ifNull(<non-String>, '')` has no ClickHouse supertype and
    `JSONExtractString` already returns a String.

    Returns (node, rewritten). When nothing is rewritten the original node comes back unchanged, so the
    caller can skip re-resolving types. Rewritten nodes are untyped; the caller re-runs type resolution.
    """
    finder = _Finder(context)
    finder.visit(node)
    rewritable = finder.extracts - _type_swapped(finder.extracts, context)
    if not rewritable:
        return node, False
    return cast(_T_AST, _Transformer(context, rewritable).visit(node)), True


def _type_swapped(extracts: set[_PropertyExtract], context: HogQLContext) -> set[_PropertyExtract]:
    """The extracts whose property PropertySwapper will retype, resolved through its own metadata loader."""
    person_names: set[str] = set()
    group_names: dict[int, set[str]] = {}
    for extract in extracts:
        if extract.bucket is None:
            continue
        kind, group_type_index = extract.bucket
        if kind == "person":
            person_names.add(extract.key)
        elif group_type_index is not None:
            group_names.setdefault(group_type_index, set()).add(extract.key)
    if context.team_id is None or not (person_names or group_names):
        return set()

    metadata = load_property_metadata(
        context,
        event_property_names=set(),
        person_property_names=person_names,
        group_property_names=group_names,
    )
    return {extract for extract in extracts if _is_type_swapped(metadata, extract)}


def _is_type_swapped(metadata: PropertyMetadata, extract: _PropertyExtract) -> bool:
    if extract.bucket is None:
        return False
    kind, group_type_index = extract.bucket
    if kind == "person":
        info = metadata.person_properties.get(extract.key)
    else:
        info = metadata.group_properties.get(f"{group_type_index}_{extract.key}")
    return (info or {}).get("type") in SWAP_TYPED_PROPERTY_TYPES


class _Finder(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.extracts: set[_PropertyExtract] = set()

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None:
            self.extracts.add(matched)
            return
        super().visit_call(node)


class _Transformer(CloningVisitor):
    def __init__(self, context: HogQLContext, rewritable: set[_PropertyExtract]):
        super().__init__(clear_types=True)
        self.context = context
        self.rewritable = rewritable

    def visit_call(self, node: ast.Call):
        matched = _matched_property_access(node, self.context)
        if matched is not None and matched in self.rewritable:
            # JSONExtractString returns '' for a missing key; property access returns NULL. Wrap in
            # ifNull(..., '') to keep that contract and the non-nullable String type.
            return ast.Call(
                name="ifNull",
                args=[ast.Field(chain=[*matched.chain, matched.key]), ast.Constant(value="")],
            )
        return super().visit_call(node)
