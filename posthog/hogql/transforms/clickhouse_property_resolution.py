"""ClickHouse pass: read each property from a faster precomputed column when one exists.

Lowering has already turned every `properties.x` read into a `PropertyAccess` node — "pull these keys out of this JSON
blob". This pass looks each one up. If the property is backed by a precomputed column (a materialized column, a dmat
column, or a property-group map), it rewrites the node to read that column instead: the same value, far cheaper than
parsing JSON. Reads with no backing column are left alone, and the printer prints them as the raw JSON extract.

It also rewrites comparisons over a backed property (`=`, `IN`, ranges, `LIKE`, is-null) to compare against the bare
column. ClickHouse can use a skip index on a plain column, but not on a value buried inside a JSON extract or an
`ifNull(...)`, so this is what keeps those queries fast.

Doing this here keeps the printer mechanical — it just prints the node it is given. What matters is identical results and
identical index usage, not identical SQL text, so verify by running the query and checking the skip-index `EXPLAIN`,
never by diffing SQL.

ClickHouse only: it runs after lowering (`prepare_ast_for_printing`) and emits ClickHouse-specific nodes, so it must
never run for the warehouse (Postgres / DuckDB) dialects.

One quirk is deliberate: an is-set check (`x IS NULL` / `x = NULL`) over a materialized property reads the column value,
so it treats both an empty string and the literal text `"null"` as "not set". This over-matches a true "does this key
exist in the blob" test, but tightening it would change query results.
"""

from dataclasses import dataclass
from typing import Literal, cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, MapStringDatabaseField
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.printer.clickhouse import AI_BLOOM_FILTER_PROPERTIES, COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.type_system import (
    ComparisonCompatibility,
    comparison_compatibility,
    constant_type_from_runtime_type,
    parse_sql_runtime_type,
    runtime_type_from_constant_type,
)
from posthog.hogql.utils import ilike_matches, like_matches
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn
from posthog.schema_enums import MaterializationMode, PropertyGroupsMode

# In non-nullable materialized columns these stored strings are treated as NULL.
MAT_COL_NULL_SENTINELS = ["", "null"]

# Leave the $ai_* bloom-filter columns to the printer: its comparison code already keeps them index-eligible
# (`COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING`, imported above so the two lists stay in sync). The value-read side skips
# their nullIf scrubbing for the same reason, via `AI_BLOOM_FILTER_PROPERTIES` (the same columns, named as properties).

_RANGE_OP_TO_CH_NAME: dict[ast.CompareOperationOp, str] = {
    ast.CompareOperationOp.Lt: "less",
    ast.CompareOperationOp.LtEq: "lessOrEquals",
    ast.CompareOperationOp.Gt: "greater",
    ast.CompareOperationOp.GtEq: "greaterOrEquals",
}


@dataclass(frozen=True)
class MaterializedPropertySource:
    """The one physical column that backs an events/persons `properties.$x` read — which column, and how to read it.

    Either a materialized column, a dmat column, or a property-group map. Carries the index metadata the comparison
    rewrites need to keep that column usable by a skip index.
    """

    kind: Literal["materialized_column", "dmat", "property_group"]
    column: str
    is_nullable: bool
    # The column's physical ClickHouse type (e.g. "Nullable(Float64)"); None means the string default. Typed columns
    # skip the string sentinel scrubbing and can be compared bare when the value side is type-compatible.
    column_type: str | None = None
    # Index metadata the comparison optimizations consult to keep the column index-eligible.
    has_minmax_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_index: bool = False
    has_bloom_filter_lower_index: bool = False


def _unwrap_to_table_type(field_type: ast.FieldType) -> ast.TableType | None:
    """The plain table type behind a field's table type, unwrapping alias and virtual-table layers."""
    table_type: ast.Type | None = field_type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        table_type = table_type.table_type
    return table_type if isinstance(table_type, ast.TableType) else None


def resolve_materialized_property_source(
    field_type: ast.FieldType, property_name: str, context: HogQLContext
) -> MaterializedPropertySource | None:
    """The physical column that backs `<events/persons>.<field>.<property_name>`, or None if nothing does.

    Tries the backing columns in priority order — a static materialized column first, then a dmat column, then the first
    property-group map column — using the same registries the old printer used. Returns None when the property has no
    backing column (so it stays a JSON read), when materialization is turned off, or when the property is access-
    restricted.
    """
    if context.modifiers.materializationMode == "disabled":
        return None

    # Property-level access control: a restricted property must never resolve to a backing column, on any path (value
    # read, comparison, key-existence). The column holds the raw value, so a comparison like `WHERE properties.x = 'y'`
    # could otherwise read it and probe the value. Declining here makes the comparison optimizers fall back; the read
    # itself becomes a constant NULL in `_substitute_value_read`.
    if property_name in restricted_property_keys_for_table_type(field_type.table_type, context):
        return None

    table_type = _unwrap_to_table_type(field_type)
    if table_type is None:
        return None

    # The materialized-column registry is keyed by the ClickHouse table name, which isn't always the HogQL name
    # (RawPersonsTable is "raw_persons" in HogQL but "person" in ClickHouse). Use the ClickHouse name, or person
    # properties would miss their materialized column and fall back to a slower JSON read.
    table_name = table_type.table.to_printed_clickhouse(context)

    field = field_type.resolve_database_field(context)
    if not isinstance(field, DatabaseField):
        # A field on a resolved table that doesn't resolve to a real column is a malformed AST. Fail loud, as the old
        # printer did here, rather than silently degrading to a raw JSON read.
        raise QueryError(f"Can't resolve field {field_type.name} on table {table_name}")
    field_name = field.name

    # 1) static materialized column (mat_* / pmat_*)
    materialized_column = get_materialized_column_for_property(
        cast(TablesWithMaterializedColumns, table_name),
        cast(TableColumn, field_name),
        cast(PropertyName, property_name),
    )
    if materialized_column is not None:
        return MaterializedPropertySource(
            kind="materialized_column",
            column=materialized_column.name,
            is_nullable=materialized_column.is_nullable,
            column_type=materialized_column.type,
            has_minmax_index=materialized_column.has_minmax_index,
            has_ngram_lower_index=materialized_column.has_ngram_lower_index,
            has_bloom_filter_index=materialized_column.has_bloom_filter_index,
            has_bloom_filter_lower_index=materialized_column.has_bloom_filter_lower_index,
        )

    # 2) dmat (dynamic materialized) slot — events.properties only, resolved from the property swapper
    if context.property_swapper is not None and table_name == "events" and field_name == "properties":
        property_info = context.property_swapper.event_properties.get(property_name)
        if property_info and (dmat_column := property_info.get("dmat")):
            return MaterializedPropertySource(kind="dmat", column=dmat_column, is_nullable=True)

    # 3) first property-group Map column for the key
    return resolve_property_group_source(field_type, property_name, context)


def resolve_property_group_source(
    field_type: ast.FieldType, property_name: str, context: HogQLContext
) -> MaterializedPropertySource | None:
    """The first property-group map column for `<events/persons>.<field>.<property_name>`, ignoring materialized columns.

    Used for key-existence (`JSONHas`), which is answered from the property group's keys bloom-filter index even when an
    individually materialized column also exists — that column can't answer key-existence, since it stores '' for both
    "absent" and "empty". `resolve_materialized_property_source` would pick the materialized column first, so JSONHas
    resolves the group directly instead.
    """
    if context.modifiers.propertyGroupsMode not in (PropertyGroupsMode.ENABLED, PropertyGroupsMode.OPTIMIZED):
        return None

    # Same access-control rule as resolve_materialized_property_source: a restricted property never resolves to a group
    # column. This guards the direct callers (JSONHas, property-group comparisons), which bypass that function.
    if property_name in restricted_property_keys_for_table_type(field_type.table_type, context):
        return None

    table_type = _unwrap_to_table_type(field_type)
    if table_type is None:
        return None

    field = field_type.resolve_database_field(context)
    if not isinstance(field, DatabaseField):
        return None

    table_name = table_type.table.to_printed_clickhouse(context)
    for group_column in property_groups.get_property_group_columns(table_name, field.name, property_name):
        return MaterializedPropertySource(kind="property_group", column=group_column, is_nullable=True)
    return None


# --- helpers to read a PropertyAccess's source column + key path -----------------------------------------------------
#
# A `PropertyAccess`'s own type is just its value type (a nullable String), so everything this pass needs comes from the
# node's structure instead: `node.expr` is the blob `Field` (its `.type` points at the table and column), and
# `node.keys` is the key path (keys[0] is the property name; deeper keys index into the extracted value).


def _blob_field_type_of(node: ast.PropertyAccess) -> ast.FieldType | None:
    """The source blob column's `FieldType` (`node.expr.type`), the input to `resolve_materialized_property_source`."""
    expr_type = node.expr.type
    return expr_type if isinstance(expr_type, ast.FieldType) else None


# --- value substitution: rebuild the printer's materialized-column read as AST ----------------------------------------


def _sentinel(value: str) -> ast.Constant:
    """A fixed scrubbing constant ('' / 'null' / the quote-trim regex / 'true' / 'false'), rendered inline not parameterized.

    `inline_sentinel` makes the printer emit the value inline (escaped), so this AST-built scrub renders identically to the
    `json_extract_trim_quotes` helper's inline string. The printer only honors it for the fixed `INLINE_SENTINEL_LITERALS`
    set. Inlining doesn't affect skip-index eligibility (that depends on the column being bare).
    """
    return ast.Constant(value=value, inline_sentinel=True)


def _augment_plain_table_type(table_type: ast.TableType, column_name: str, is_nullable: bool) -> ast.TableType:
    table = table_type.table
    if table.has_field(column_name):
        return table_type
    synthetic = DatabaseField(name=column_name, nullable=is_nullable)
    augmented = table.model_copy(update={"fields": {**table.fields, column_name: synthetic}})
    return ast.TableType(table=augmented)


def _augment_table_type(
    table_type: ast.Type, column_name: str, *, is_nullable: bool
) -> ast.TableType | ast.TableAliasType | None:
    if isinstance(table_type, ast.VirtualTableType):
        # PoE person properties: the physical mat/group columns live on the underlying events table.
        return _augment_table_type(table_type.table_type, column_name, is_nullable=is_nullable)
    if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        inner = table_type.table_type
        if not isinstance(inner, ast.TableType):
            return None
        return ast.TableAliasType(
            alias=table_type.alias, table_type=_augment_plain_table_type(inner, column_name, is_nullable)
        )
    if isinstance(table_type, ast.TableType):
        return _augment_plain_table_type(table_type, column_name, is_nullable)
    return None


def _synthetic_column_field(field_type: ast.FieldType, column_name: str, *, is_nullable: bool) -> ast.Field | None:
    """A typed `Field` for a physical ClickHouse column that the HogQL schema doesn't know about.

    Materialized / dmat / property-group columns exist on the table but aren't in the HogQL schema, so a plain `Field`
    can't resolve to them. Build a fake `DatabaseField` on a copy of the table and point a fresh `FieldType` at it,
    keeping any table alias so the printed prefix (`events.` / `e.`) is unchanged.
    """
    table_type = _augment_table_type(field_type.table_type, column_name, is_nullable=is_nullable)
    if table_type is None:
        return None
    return ast.Field(
        chain=[column_name],
        type=ast.FieldType(name=column_name, table_type=table_type),
    )


def _materialized_head_expr(
    source: MaterializedPropertySource,
    field_type: ast.FieldType,
    first_key: str,
    *,
    is_single: bool,
    materialization_mode: MaterializationMode | None,
) -> ast.Expr | None:
    """The read for the top-level key (chain[0]) from a backing column: a property-group map lookup, or a scrubbed column."""
    if source.kind == "property_group":
        # has(map, key) ? map[key] : null — guard the map read so a missing key returns NULL, not the map's '' default.
        has_field = _synthetic_column_field(field_type, source.column, is_nullable=True)
        get_field = _synthetic_column_field(field_type, source.column, is_nullable=True)
        if has_field is None or get_field is None:
            return None
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="has", args=[has_field, ast.Constant(value=first_key)]),
                ast.ArrayAccess(array=get_field, property=ast.Constant(value=first_key)),
                ast.Constant(value=None),
            ],
        )

    column_field = _synthetic_column_field(field_type, source.column, is_nullable=source.is_nullable)
    if column_field is None:
        return None

    # Nullable columns (dmat, nullable mat) and the index-friendly $ai single-key columns are read bare.
    if source.is_nullable or (is_single and first_key in AI_BLOOM_FILTER_PROPERTIES):
        return column_field

    # A typed (non-string) column has no string sentinels to scrub — wrapping it in nullIf(col, '') would not even
    # type-check in ClickHouse — so it is read bare as well.
    if not _is_string_column(source):
        return column_field

    # Non-nullable materialized column: scrub the '' / 'null' string sentinels back to NULL.
    scrubbed_empty = ast.Call(name="nullIf", args=[column_field, _sentinel("")])
    if materialization_mode == MaterializationMode.LEGACY_NULL_AS_STRING:
        return scrubbed_empty
    return ast.Call(name="nullIf", args=[scrubbed_empty, _sentinel("null")])


def _map_value_read(blob: ast.Expr, key: str) -> ast.Expr:
    """`has(map, key) ? map[key] : null` for a physical ClickHouse Map column — a missing key reads NULL, not ''."""
    return ast.Call(
        name="if",
        args=[
            ast.Call(name="has", args=[clone_expr(blob), ast.Constant(value=key)]),
            ast.ArrayAccess(array=clone_expr(blob), property=ast.Constant(value=key)),
            ast.Constant(value=None),
        ],
    )


def _substitute_value_read(node: ast.PropertyAccess, context: HogQLContext) -> ast.Expr | None:
    """The backing-column read for a `PropertyAccess`, or None to leave it as the JSON extract.

    Picks the column and builds the read (the numeric/boolean cast is not handled here — it already wraps this node).
    Returns a constant NULL for an access-restricted property, or None when the property has no precomputed column
    (materialized, dmat, or property group) to read from — in which case it stays a raw JSON extract.
    """
    field_type = _blob_field_type_of(node)
    # Lowering builds every PropertyAccess with the blob FieldType on `expr` and a non-empty key path. Assert the
    # invariant rather than silently bailing, so a real violation fails loud instead of degrading to a JSON read.
    assert field_type is not None and node.keys

    first_key = str(node.keys[0])
    deeper_keys: list[str | int] = list(node.keys[1:])

    # Access control: a restricted property reads as NULL. The blob path would compute the same value — the printer's
    # JSONDropKeys strips the key, so extracting it always yields '' which scrubs to NULL — so return that constant
    # directly and skip the wasted drop-then-extract. (The column resolvers also decline, so comparisons over a
    # restricted property never read the backing column either; their operand falls through to this same NULL.)
    if first_key in restricted_property_keys_for_table_type(field_type.table_type, context):
        _record_property_usage(context, None)
        return ast.Constant(value=None, type=ast.StringType(nullable=True))

    source = resolve_materialized_property_source(field_type, first_key, context)
    if source is None:
        # A physical Map column (logs/spans/metrics attributes) reads an un-grouped key via map subscript — the JSON
        # fallback would print JSONExtract, which ClickHouse rejects on a Map. Plain JSON blobs (events.properties)
        # keep the JSON fallback.
        if isinstance(field_type.resolve_database_field(context), MapStringDatabaseField):
            _record_property_usage(context, "map_subscript")
            map_head = _map_value_read(node.expr, first_key)
            if not deeper_keys:
                return map_head
            return ast.PropertyAccess(expr=map_head, keys=deeper_keys, type=ast.StringType(nullable=True))
        _record_property_usage(context, None)
        return None
    _record_property_usage(context, source.kind)

    head = _materialized_head_expr(
        source,
        field_type,
        first_key,
        is_single=not deeper_keys,
        materialization_mode=context.modifiers.materializationMode,
    )
    if head is None:
        return None
    if not deeper_keys:
        return head
    # Deeper keys read the column value as a JSON string. Emit a PropertyAccess rather than building the extract here:
    # the printer renders that node via `json_extract_trim_quotes` (kafka_engine.py), the one implementation of the
    # extract-and-trim SQL shape.
    return ast.PropertyAccess(expr=head, keys=deeper_keys, type=ast.StringType(nullable=True))


# --- comparison rewrites: keep the bare column eligible for skip indexes -----------------------------------------------
#
# By default a property comparison reads the materialized column wrapped in null-scrubbing functions
# (replaceRegexpAll(nullIf(nullIf(...)))). ClickHouse can't use the column's skip index through that wrapping, so it
# scans every row. When one side of a comparison is a property with a materialized column (or a property-group map
# entry), these rewrites rebuild the comparison against the bare column instead, restoring the empty/null handling
# inline so the rows are unchanged. The bare column is index-eligible, so ClickHouse can skip granules.


def _call(name: str, args: list[ast.Expr]) -> ast.Call:
    return ast.Call(name=name, args=args)


def _const(value: object) -> ast.Constant:
    return ast.Constant(value=value)


def _lower(expr: ast.Expr) -> ast.Call:
    """`lower(expr)`, typed non-nullable String so the printer doesn't ifNull-wrap a comparison against it."""
    return ast.Call(name="lower", args=[expr], type=ast.StringType(nullable=False))


def _coalesce_empty(expr: ast.Expr) -> ast.Call:
    """`coalesce(expr, '')`, typed non-nullable String — matches the lower-index expression and prints bare."""
    return ast.Call(name="coalesce", args=[expr, _sentinel("")], type=ast.StringType(nullable=False))


def _string_pattern_constant(expr: ast.Expr) -> ast.Constant | None:
    return expr if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _column_constant_type(source: MaterializedPropertySource) -> ast.ConstantType:
    """The backing column's physical ClickHouse type as a ConstantType; an untyped column is the string default."""
    return constant_type_from_runtime_type(parse_sql_runtime_type(source.column_type or "String"))


def _is_string_column(source: MaterializedPropertySource) -> bool:
    return isinstance(_column_constant_type(source), ast.StringType)


# Comparison compatibilities the rewrites accept: provably comparable as-is, or via a cast ClickHouse does cheaply.
_OPTIMIZER_COMPATIBLE_COMPARISONS = {
    ComparisonCompatibility.DEFINITELY_COMPATIBLE,
    ComparisonCompatibility.CHEAP_CAST,
}


# The fired subset of the range-rewrite outcomes (`_RANGE_REWRITE_RESULTS` in observability.py). Kept explicit so a
# future outcome label opts into the usage side effect below deliberately rather than via a name prefix.
_FIRED_RANGE_REWRITE_RESULTS = frozenset({"fired_compare", "fired_if_null"})


def _record_range_rewrite(context: HogQLContext, result: str) -> None:
    if context.type_observability is None:
        return
    context.type_observability.record_materialized_range_rewrite(result)
    if result in _FIRED_RANGE_REWRITE_RESULTS:
        # A fired rewrite reads the materialized column directly, bypassing the value-substitution path that normally
        # accounts for the materialized access, so record the usage here.
        context.type_observability.record_materialized_property_usage("materialized_column")


_USAGE_BY_SOURCE_KIND = {
    "materialized_column": "materialized_column",
    "dmat": "dynamic_materialized_column",
    "property_group": "property_group",
    "map_subscript": "map_subscript",
}


def _record_property_usage(context: HogQLContext, kind: str | None) -> None:
    """Record how a property value read was served: from a backing column kind, or "json" when none backs it."""
    if context.type_observability is None:
        return
    context.type_observability.record_materialized_property_usage(_USAGE_BY_SOURCE_KIND.get(kind or "", "json"))


@dataclass(frozen=True)
class _OptimizableProperty:
    """A single-key property used in a comparison, paired with the physical column that backs it.

    `field_type` is the blob column's type, `key` is the property name, and `source` is the backing column. The methods
    build the column expressions the comparison optimizers compare against.
    """

    field_type: ast.FieldType
    key: str
    source: MaterializedPropertySource

    def bare_column(self) -> ast.Field:
        """The backing column as a bare `Field`, typed non-nullable.

        Non-nullable typing stops the printer from `ifNull`-wrapping the comparison — the wrapping that hides the column
        from skip indexes. A genuinely Nullable column is guarded separately (see `is_not_null`). This doubles as the
        map column for a property group, where a missing key reads as the '' default rather than SQL NULL.
        """
        field = _synthetic_column_field(self.field_type, self.source.column, is_nullable=False)
        assert field is not None  # the source was resolved from this same field_type
        return field

    def is_not_null(self) -> ast.Call:
        """`isNotNull(col)` over the nullable read of the column — guards a bare comparison against NULL rows."""
        field = _synthetic_column_field(self.field_type, self.source.column, is_nullable=True)
        assert field is not None
        return _call("isNotNull", [field])

    def group_has(self) -> ast.Call:
        """`has(map_column, key)` — true when the property group contains the key (uses the keys bloom-filter index)."""
        return _call("has", [self.bare_column(), _const(self.key)])

    def group_value(self) -> ast.ArrayAccess:
        """`map_column[key]`, typed non-nullable String — the property's value from the group map.

        A missing key reads as the '' default, never SQL NULL; the non-nullable type keeps `equals(map[key], v)` out of
        an `ifNull` wrapper so the values bloom-filter index still applies.
        """
        return ast.ArrayAccess(array=self.bare_column(), property=_const(self.key), type=ast.StringType(nullable=False))


class ClickHousePropertyResolver(CloningVisitor):
    """Rewrites lowered `PropertyAccess` reads (and comparisons over them) to read backing columns where they exist.

    After this pass, a backed property is an ordinary column expression; an unbacked (or restricted) one stays a
    `PropertyAccess` and prints as the raw JSON extract.
    """

    def __init__(self, context: HogQLContext) -> None:
        # The AST is printed directly after this pass, so keep resolved types rather than clearing them.
        super().__init__(clear_types=False)
        self.context = context
        # Identity set of the table types in scope for the SELECT currently being visited (its FROM/JOIN chain,
        # including the layers behind alias/virtual wrappers). Guards the comparison rewrites: a rewrite reads a real
        # table column, which is only printable when that table is in the current FROM. A property read that an earlier
        # transform moved behind a subquery (events predicate pushdown) must decline instead.
        self._tables_in_scope: list[set[int]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        scope: set[int] = set()
        join: ast.JoinExpr | None = node.select_from
        while join is not None:
            table_type: ast.Type | None = join.table.type if join.table is not None else None
            while table_type is not None:
                scope.add(id(table_type))
                table_type = getattr(table_type, "table_type", None)
            join = join.next_join
        self._tables_in_scope.append(scope)
        try:
            return super().visit_select_query(node)
        finally:
            self._tables_in_scope.pop()

    def _property_table_in_scope(self, field_type: ast.FieldType) -> bool:
        """True if the property's source table is in the current SELECT's FROM/JOIN chain (by object identity)."""
        if not self._tables_in_scope:
            # A bare fragment (within_non_hogql_query) has no SELECT scope, and no transform that could move a read
            # behind a subquery runs on fragments — treat it as in scope.
            return True
        scope = self._tables_in_scope[-1]
        table_type: ast.Type | None = field_type.table_type
        while table_type is not None:
            if id(table_type) in scope:
                return True
            table_type = getattr(table_type, "table_type", None)
        return False

    def _lowered_property_operand(self, expr: ast.Expr) -> ast.PropertyAccess | None:
        """The lowered `properties.$x` behind a comparison operand, or None.

        After lowering, such an operand is a `PropertyAccess` (often wrapped in an `Alias`).
        """
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        if isinstance(expr, ast.PropertyAccess):
            return expr
        return None

    def _single_key_property(self, expr: ast.Expr) -> tuple[ast.FieldType, str] | None:
        """The (blob `FieldType`, property name) of a single-key property operand, or None.

        Only a single-key access (`properties.x`, no deeper `.a.b`) maps to one backing column. A multi-key access reads
        the column and then JSON-extracts deeper, so it can't use the bare-column comparison rewrites.
        """
        node = self._lowered_property_operand(expr)
        if node is not None and len(node.keys) == 1:
            field_type = _blob_field_type_of(node)
            if field_type is not None:
                return field_type, str(node.keys[0])

        # The operand can also carry the property on its resolved type rather than as a bare `PropertyAccess`: a
        # reference to a select alias over a property read (`SELECT properties.x AS a ... WHERE a = 'v'`) resolves
        # through the alias wrapper to the original `PropertyType`, and a boolean/numeric property gets wrapped by the
        # swapper in a cast (`toBool(transform(toString(...)))`) with the `PropertyType` underneath. Read the property
        # identity off the type — that is the resolver's own binding, so a shadowing alias of the same name can never
        # be confused with it (its type points at whatever it actually aliases). Skip joined-subquery properties
        # (lowering skips them too: they print as `alias.field`) and properties whose table is not in the current
        # FROM (a transform moved the read behind a subquery; the bare column would be out of scope).
        prop_type = resolve_field_type(expr)
        if (
            isinstance(prop_type, ast.PropertyType)
            and len(prop_type.chain) == 1
            and prop_type.joined_subquery is None
            and self._property_table_in_scope(prop_type.field_type)
        ):
            return prop_type.field_type, str(prop_type.chain[0])
        return None

    # --- value substitution ---

    def visit_property_access(self, node: ast.PropertyAccess) -> ast.Expr:
        substituted = _substitute_value_read(node, self.context)
        if substituted is not None:
            return substituted
        return super().visit_property_access(node)

    # --- comparison / call rewrites ---

    def visit_call(self, node: ast.Call) -> ast.Expr:
        # `isNull` / `isNotNull` / `JSONHas` on a property-group property can be answered by `has(map, key)` alone,
        # without reading the values subcolumn — so it stays eligible for the keys bloom-filter index.
        optimized = self._optimize_property_group_call(node)
        if optimized is not None:
            return optimized

        # A comparison written in call form (`equals(properties.x, v)`, `ilike(toString(properties.x), p)`,
        # `in(properties.x, (...))`) is still a comparison: route it through visit_compare_operation so the same rewrites
        # fire. Otherwise we'd descend into the args and substitute the value, losing the optimization. Only the plain
        # 2-arg form, no extra params.
        if (
            node.name in HOGQL_COMPARISON_MAPPING
            and len(node.args) == 2
            and node.params is None
            and node.distinct is False
            and node.within_group is None
            and node.order_by is None
            and node.filter_expr is None
        ):
            return self.visit_compare_operation(
                ast.CompareOperation(left=node.args[0], right=node.args[1], op=HOGQL_COMPARISON_MAPPING[node.name])
            )

        return super().visit_call(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        # Try each skip-index comparison rewrite in order. Each one consumes the property operand and returns the
        # rewritten comparison, so once one matches we must NOT also substitute the value. (session_id is left to the
        # printer — it optimizes a real column, not a property.)
        optimized = (
            self._optimize_property_group_compare(node)
            or self._optimize_materialized_equals(node)
            or self._optimize_materialized_range(node)
            or self._optimize_materialized_ilike(node)
            or self._optimize_materialized_like(node)
            or self._optimize_materialized_in(node)
            or self._optimize_materialized_lower_in(node)
        )
        if optimized is not None:
            return optimized

        # Intentional gap: nothing above rewrites `property = NULL` / `!= NULL`, so it falls through to super() and the
        # surviving PropertyAccess reads the scrubbed materialized column. An is-set check therefore treats both an empty
        # string and the literal text "null" as "not set", which over-matches a true "does this key exist in the blob"
        # test. Left this way deliberately — tightening it would change query results.
        return super().visit_compare_operation(node)

    # --- property operand detection ---

    def _materialized_string_property(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key string property backed by an individually materialized column, or None.

        Unwraps a `toString(properties.x)` wrapper, requires a single key, skips properties whose resolved type isn't a
        string, and requires a materialized column (not a property group). The plain and `toString(...)` forms both
        resolve to the same lowered property.
        """
        single = self._single_key_property(expr)
        if single is None and isinstance(expr, ast.Call) and expr.name == "toString" and len(expr.args) == 1:
            # Only a direct lowered property read, not toString(toFloat(...)): the inner arg must itself be the property.
            single = self._single_key_property(expr.args[0])
        if single is None:
            return None
        field_type, property_name = single

        if self.context.property_swapper is not None:
            prop_info = self.context.property_swapper.event_properties.get(property_name)
            if prop_info is not None and prop_info.get("type") not in (None, "String"):
                return None

        source = resolve_materialized_property_source(field_type, property_name, self.context)
        if source is None or source.kind not in ("materialized_column", "dmat") or not _is_string_column(source):
            return None
        return _OptimizableProperty(
            field_type=field_type,
            key=property_name,
            source=source,
        )

    def _materialized_property_for_op(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key materialized-column property (any resolved type), for IN comparisons that don't need a string."""
        single = self._single_key_property(expr)
        if single is None:
            return None
        field_type, property_name = single
        source = resolve_materialized_property_source(field_type, property_name, self.context)
        if source is None or source.kind not in ("materialized_column", "dmat") or not _is_string_column(source):
            return None
        return _OptimizableProperty(
            field_type=field_type,
            key=property_name,
            source=source,
        )

    def _property_group_property(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key property backed by a property group, only under OPTIMIZED mode."""
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None
        single = self._single_key_property(expr)
        if single is None:
            return None
        field_type, property_name = single
        source = resolve_materialized_property_source(field_type, property_name, self.context)
        if source is None or source.kind != "property_group":
            return None
        return _OptimizableProperty(
            field_type=field_type,
            key=property_name,
            source=source,
        )

    @staticmethod
    def _is_ai_column(source: MaterializedPropertySource) -> bool:
        return source.column.strip("`\"'") in COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING

    # --- property-group optimizers ---

    def _optimize_property_group_call(self, node: ast.Call) -> ast.Expr | None:
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        if node.name in ("isNull", "isNotNull") and len(node.args) == 1:
            prop = self._property_group_property(node.args[0])
            if prop is None:
                return None
            has_expr = prop.group_has()
            return _call("not", [has_expr]) if node.name == "isNull" else has_expr

        if node.name == "JSONHas" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            # JSONHas(blob, key): the key is the literal second arg, and the first arg is the blob Field. Resolve the
            # property group for that key off the blob's FieldType.
            field_expr = node.args[0]
            field_type = resolve_field_type(field_expr)
            if not isinstance(field_type, ast.FieldType):
                return None
            key = str(node.args[1].value)
            # Key-existence is answered from the property group even when a materialized column also exists, so resolve
            # the group directly — the mat-column-first resolver would otherwise shadow it.
            source = resolve_property_group_source(field_type, key, self.context)
            if source is None or source.kind != "property_group":
                return None
            return _OptimizableProperty(
                field_type=field_type,
                key=key,
                source=source,
            ).group_has()

        return None

    def _optimize_property_group_compare(self, node: ast.CompareOperation) -> ast.Expr | None:
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            return self._optimize_property_group_eq(node)
        if node.op == ast.CompareOperationOp.In:
            return self._optimize_property_group_in(node)
        return None

    def _optimize_property_group_eq(self, node: ast.CompareOperation) -> ast.Expr | None:
        prop: _OptimizableProperty | None = None
        constant_expr: ast.Constant | None = None
        if isinstance(node.right, ast.Constant):
            prop = self._property_group_property(node.left)
            constant_expr = node.right
        elif isinstance(node.left, ast.Constant):
            prop = self._property_group_property(node.right)
            constant_expr = node.left
        if prop is None or constant_expr is None:
            return None

        value = constant_expr.value
        if node.op == ast.CompareOperationOp.Eq:
            if value is None:
                # `= NULL` means the key is absent: not(has(map, key)). Avoids reading the values subcolumn.
                return _call("not", [prop.group_has()])
            if value is True:
                # Booleans are stored as the strings 'true'/'false' in the group map; compare against those so the
                # comparison stays index-eligible.
                return _call("equals", [prop.group_value(), _sentinel("true")])
            if value is False:
                return _call("equals", [prop.group_value(), _sentinel("false")])
            if isinstance(constant_expr.type, ast.StringType):
                eq = _call("equals", [prop.group_value(), _const(value)])
                if value == "":
                    # '' is also the map's default for an absent key, so also check the key is present.
                    return _call("and", [prop.group_has(), eq])
                return eq
            return None

        # NotEq
        if value is None:
            # `!= NULL` means the key is present: has(map, key). Uses the keys index, skips the values subcolumn.
            return prop.group_has()
        return None

    def _optimize_property_group_in(self, node: ast.CompareOperation) -> ast.Expr | None:
        # IN is not commutative; only the left operand can be the property.
        prop = self._property_group_property(node.left)
        if prop is None:
            return None

        if isinstance(node.right, ast.Constant):
            value = node.right.value
            if value is None:
                return None  # IN (NULL) is true if the key is absent OR the value is null — can't shortcut
            if value == "":
                return _call("and", [prop.group_has(), _call("equals", [prop.group_value(), _const("")])])
            if isinstance(node.right.type, ast.StringType):
                return _call("equals", [prop.group_value(), _const(value)])
            return None
        if isinstance(node.right, (ast.Tuple, ast.Array)):
            return self._optimize_group_in_with_values(node.right.exprs, prop)
        return None

    def _optimize_group_in_with_values(self, values: list[ast.Expr], prop: _OptimizableProperty) -> ast.Expr | None:
        # Bail on any non-string / empty / NULL value — those can't use the bare-column form.
        string_values: list[str] = []
        for v in values:
            if not isinstance(v, ast.Constant) or v.value == "" or v.value is None or not isinstance(v.value, str):
                return None
            string_values.append(v.value)
        if len(string_values) == 0:
            return _const(False)  # IN () is always false
        if len(string_values) == 1:
            return _call("equals", [prop.group_value(), _const(string_values[0])])
        # ClickHouse's transform_null_in setting makes `in(map[key], ...)` skip the keys index; the has() guard restores it.
        in_expr = _call("in", [prop.group_value(), ast.Tuple(exprs=[_const(v) for v in string_values])])
        return _call("and", [prop.group_has(), in_expr])

    # --- individually-materialized-column optimizers ---

    def _optimize_materialized_equals(self, node: ast.CompareOperation) -> ast.Expr | None:
        if node.op not in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            return None

        prop: _OptimizableProperty | None = None
        constant_expr: ast.Constant | None = None
        if (p := self._materialized_string_property(node.left)) and (c := _string_pattern_constant(node.right)):
            prop, constant_expr = p, c
        elif (p := self._materialized_string_property(node.right)) and (c := _string_pattern_constant(node.left)):
            prop, constant_expr = p, c
        if prop is None or constant_expr is None:
            return None

        if constant_expr.value in MAT_COL_NULL_SENTINELS:
            return None  # comparing against '' / 'null' itself: let the normal scrubbed read handle it
        if self._is_ai_column(prop.source):
            return None  # the printer handles the $ai columns

        column = prop.bare_column()
        value = _const(constant_expr.value)
        if node.op == ast.CompareOperationOp.Eq:
            eq = _call("equals", [column, value])
            if prop.source.is_nullable:
                return _call("and", [eq, prop.is_not_null()])
            return eq
        # NotEq
        neq = _call("notEquals", [column, value])
        if prop.source.is_nullable:
            return _call("ifNull", [neq, _const(True)])
        return neq

    def _optimize_materialized_range(self, node: ast.CompareOperation) -> ast.Expr | None:
        op_name = _RANGE_OP_TO_CH_NAME.get(node.op)
        if op_name is None:
            return None
        # the column is always the left operand here, so only that side is handled.
        prop = self._materialized_string_property(node.left)
        if prop is None:
            return self._optimize_typed_materialized_range(node, op_name)
        if not isinstance(node.right, ast.Constant) or node.right.value is None:
            _record_range_rewrite(self.context, "skipped")
            return None
        if self._is_ai_column(prop.source):
            _record_range_rewrite(self.context, "skipped")
            return None

        cmp = _call(op_name, [prop.bare_column(), _const(node.right.value)])
        if prop.source.is_nullable:
            _record_range_rewrite(self.context, "fired_if_null")
            return _call("and", [cmp, prop.is_not_null()])
        # Non-nullable: exclude the '' / 'null' sentinels inline so the bare comparison stays index-eligible.
        _record_range_rewrite(self.context, "fired_compare")
        clauses: list[ast.Expr] = [cmp]
        clauses.extend(_call("notEquals", [prop.bare_column(), _sentinel(s)]) for s in MAT_COL_NULL_SENTINELS)
        return _call("and", clauses)

    def _optimize_typed_materialized_range(self, node: ast.CompareOperation, op_name: str) -> ast.Expr | None:
        """Range over a property backed by a typed (non-string) materialized column: compare the bare column.

        A typed column stores the property in its real type (e.g. `Nullable(Float64)`, `Nullable(DateTime64)`), so when
        the property's semantic type matches the column and the value side is comparable, the comparison can read the
        bare column — no cast wrapper, no sentinel scrub — which keeps it eligible for the column's minmax index. A
        string value compared against a DateTime column is converted with `toDateTime64(value, 6, tz)` so the column
        side stays bare. Only nullable typed columns rewrite: a non-nullable typed column stores the ClickHouse type
        default for a missing property, and a bare comparison could not tell a real default from a missing value.
        """
        single = self._single_key_property(node.left)
        if single is None:
            return None
        field_type, property_name = single
        source = resolve_materialized_property_source(field_type, property_name, self.context)
        if source is None:
            return None  # no backing column — not a rewrite candidate, nothing to record
        if source.kind != "materialized_column" or _is_string_column(source):
            # The backing column stores the value as a string (string mat column, dmat, or property-group map), where a
            # bare range comparison would order lexicographically — unsafe, so the rewrite is skipped. This is the
            # common shape: numeric/datetime properties materialize to string columns unless a typed column was created.
            _record_range_rewrite(self.context, "skipped")
            return None

        physical = _column_constant_type(source)
        semantic = self._operand_semantic_type(node.left)
        if semantic is None or comparison_compatibility(semantic, physical) not in _OPTIMIZER_COMPATIBLE_COMPARISONS:
            _record_range_rewrite(self.context, "skipped")
            return None

        right_constant = node.right if isinstance(node.right, ast.Constant) else None
        if right_constant is not None and right_constant.value is None:
            _record_range_rewrite(self.context, "skipped")
            return None

        value_type = self._operand_semantic_type(node.right)
        converts_to_datetime = (
            right_constant is not None
            and value_type is not None
            and runtime_type_from_constant_type(physical).family == "datetime"
            and runtime_type_from_constant_type(value_type).family == "string"
        )
        if not converts_to_datetime and (
            value_type is None
            or comparison_compatibility(physical, value_type) not in _OPTIMIZER_COMPATIBLE_COMPARISONS
        ):
            _record_range_rewrite(self.context, "skipped")
            return None

        if not source.is_nullable:
            _record_range_rewrite(self.context, "skipped")
            return None

        right_expr = cast(ast.Expr, self.visit(node.right))
        if converts_to_datetime:
            right_expr = _call("toDateTime64", [right_expr, _const(6), ast.Constant(value=self._project_timezone())])

        column = _OptimizableProperty(field_type=field_type, key=property_name, source=source)
        cmp = _call(op_name, [column.bare_column(), right_expr])
        _record_range_rewrite(self.context, "fired_if_null")  # always nullable here, so the rewrite is null-guarded
        return _call("and", [cmp, column.is_not_null()])

    def _operand_semantic_type(self, expr: ast.Expr) -> ast.ConstantType | None:
        """The semantic type of a comparison operand: the property's registered type for a property read (read off the
        resolver's `PropertyType` binding, which survives the swapper's cast wrapper), or the expression's own resolved
        type. A bare lowered JSON read is semantically a string."""
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        if isinstance(expr, ast.PropertyAccess):
            return expr.type if isinstance(expr.type, ast.ConstantType) else ast.StringType(nullable=True)
        expr_type = resolve_field_type(expr)
        if expr_type is None:
            return None
        try:
            return expr_type.resolve_constant_type(self.context)
        except Exception:
            return None

    def _project_timezone(self) -> str:
        if self.context.modifiers.convertToProjectTimezone is False:
            return "UTC"
        return self.context.database.get_timezone() if self.context.database else "UTC"

    def _optimize_materialized_ilike(self, node: ast.CompareOperation) -> ast.Expr | None:
        if node.op not in (ast.CompareOperationOp.ILike, ast.CompareOperationOp.NotILike):
            return None
        prop = self._materialized_string_property(node.left)
        pattern = _string_pattern_constant(node.right)
        if prop is None or pattern is None:
            return None

        is_ilike = node.op == ast.CompareOperationOp.ILike
        if prop.source.is_nullable:
            if is_ilike:
                if prop.source.has_ngram_lower_index:
                    # Match the ngram_lower index expression: like(lower(coalesce(col, '')), lower(pattern)).
                    indexed = _lower(_coalesce_empty(prop.bare_column()))
                    return _call("and", [_call("like", [indexed, _lower(_const(pattern.value))]), prop.is_not_null()])
                return _call("and", [_call("ilike", [prop.bare_column(), _const(pattern.value)]), prop.is_not_null()])
            return _call("ifNull", [_call("notILike", [prop.bare_column(), _const(pattern.value)]), _const(True)])

        # Non-nullable: bail if the pattern could match a stored sentinel.
        if any(ilike_matches(cast(str, pattern.value), s) for s in MAT_COL_NULL_SENTINELS):
            return None
        if is_ilike:
            if prop.source.has_ngram_lower_index:
                return _call("like", [_lower(prop.bare_column()), _lower(_const(pattern.value))])
            return _call("ilike", [prop.bare_column(), _const(pattern.value)])
        return _call("notILike", [prop.bare_column(), _const(pattern.value)])

    def _optimize_materialized_like(self, node: ast.CompareOperation) -> ast.Expr | None:
        if node.op not in (ast.CompareOperationOp.Like, ast.CompareOperationOp.NotLike):
            return None
        prop = self._materialized_string_property(node.left)
        pattern = _string_pattern_constant(node.right)
        if prop is None or pattern is None:
            return None

        is_like = node.op == ast.CompareOperationOp.Like
        if prop.source.is_nullable:
            if is_like:
                return _call("and", [_call("like", [prop.bare_column(), _const(pattern.value)]), prop.is_not_null()])
            return _call("ifNull", [_call("notLike", [prop.bare_column(), _const(pattern.value)]), _const(True)])

        if any(like_matches(cast(str, pattern.value), s) for s in MAT_COL_NULL_SENTINELS):
            return None
        if is_like:
            return _call("like", [prop.bare_column(), _const(pattern.value)])
        return _call("notLike", [prop.bare_column(), _const(pattern.value)])

    def _optimize_materialized_in(self, node: ast.CompareOperation) -> ast.Expr | None:
        if node.op not in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            return None
        prop = self._materialized_property_for_op(node.left)
        if prop is None or self._is_ai_column(prop.source):
            return None

        values = self._extract_string_constants(node.right)
        if not values:
            return None

        if prop.source.is_nullable:
            if node.op == ast.CompareOperationOp.In:
                # ClickHouse's transform_null_in makes in() hard to index; flip to has([...], col) (safe: NULL already excluded).
                array = ast.Array(exprs=[_const(v) for v in values])
                return _call("and", [_call("has", [array, prop.bare_column()]), prop.is_not_null()])
            tup = ast.Tuple(exprs=[_const(v) for v in values])
            return _call("ifNull", [_call("notIn", [prop.bare_column(), tup]), _const(True)])

        # non-nullable: bail if any value is a stored sentinel.
        if any(v in MAT_COL_NULL_SENTINELS for v in values):
            return None
        if node.op == ast.CompareOperationOp.In:
            array = ast.Array(exprs=[_const(v) for v in values])
            return _call("has", [array, prop.bare_column()])
        tup = ast.Tuple(exprs=[_const(v) for v in values])
        return _call("notIn", [prop.bare_column(), tup])

    def _optimize_materialized_lower_in(self, node: ast.CompareOperation) -> ast.Expr | None:
        if node.op not in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            return None
        # HogQL `lower` is case-insensitive on the Call name.
        if not (isinstance(node.left, ast.Call) and node.left.name.lower() == "lower" and len(node.left.args) == 1):
            return None
        prop = self._materialized_string_property(node.left.args[0])
        if prop is None or not (prop.source.has_bloom_filter_lower_index or prop.source.has_ngram_lower_index):
            return None
        if self._is_ai_column(prop.source):
            return None

        values = self._extract_lower_in_values(node.right)
        if not values:
            return None

        # Bail if a value could collide with a stored NULL sentinel.
        null_sentinels = [""] if prop.source.is_nullable else MAT_COL_NULL_SENTINELS
        if any(v in null_sentinels for v in values):
            return None

        if prop.source.is_nullable:
            indexed: ast.Expr = _lower(_coalesce_empty(prop.bare_column()))
        else:
            indexed = _lower(prop.bare_column())

        if node.op == ast.CompareOperationOp.In:
            return _call("has", [ast.Array(exprs=[_const(v) for v in values]), indexed])
        return _call("notIn", [indexed, ast.Tuple(exprs=[_const(v) for v in values])])

    @staticmethod
    def _extract_string_constants(node: ast.Expr) -> list[str] | None:
        """A list of string values from an IN right-hand side (single constant or tuple/array of constants)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.Tuple, ast.Array)):
            values: list[str] = []
            for value in node.exprs:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    values.append(value.value)
                else:
                    return None
            return values or None
        return None

    @staticmethod
    def _extract_lower_in_values(node: ast.Expr) -> list[str] | None:
        """Like _extract_string_constants but also accepts a constant list (from a `{placeholder}`)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Constant) and isinstance(node.value, (list, tuple)):
            if not all(isinstance(value, str) for value in node.value):
                return None
            return list(node.value) or None
        if isinstance(node, (ast.Tuple, ast.Array)):
            values: list[str] = []
            for value in node.exprs:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    values.append(value.value)
                else:
                    return None
            return values or None
        return None


def clickhouse_property_resolution(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Rewrite every backed lowered `PropertyAccess` (and comparison over it) to read its backing column.

    ClickHouse only. Expects a resolved, swapped, lowered AST, and runs right after `lower_property_access` in the
    ClickHouse print pipeline (see `prepare_ast_for_printing`).
    """
    return cast(_T_AST, ClickHousePropertyResolver(context).visit(node))
