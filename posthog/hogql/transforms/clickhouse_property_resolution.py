"""ClickHouse pass: read each property from a faster precomputed column when one exists.

Lowering has already turned every `properties.x` read into a `JSONFieldAccess` node — "pull these keys out of this JSON
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

from posthog.schema import MaterializationMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.printer.clickhouse import AI_BLOOM_FILTER_PROPERTIES, COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.utils import ilike_matches, like_matches
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn

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
    # read, comparison, key-existence). The column holds the raw value and bypasses the printer's JSONDropKeys blob
    # scrub, so reading or comparing it directly would leak the value. Declining here forces the scrubbed JSON path.
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


# --- helpers to read a JSONFieldAccess's source column + key path -----------------------------------------------------
#
# A `JSONFieldAccess`'s own type is just its value type (a nullable String), so everything this pass needs comes from the
# node's structure instead: `node.expr` is the blob `Field` (its `.type` points at the table and column), and
# `node.keys` is the key path (keys[0] is the property name; deeper keys index into the extracted value).


def _blob_field_type_of(node: ast.JSONFieldAccess) -> ast.FieldType | None:
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

    # Non-nullable materialized column: scrub the '' / 'null' string sentinels back to NULL.
    scrubbed_empty = ast.Call(name="nullIf", args=[column_field, _sentinel("")])
    if materialization_mode == MaterializationMode.LEGACY_NULL_AS_STRING:
        return scrubbed_empty
    return ast.Call(name="nullIf", args=[scrubbed_empty, _sentinel("null")])


def _substitute_value_read(node: ast.JSONFieldAccess, context: HogQLContext) -> ast.Expr | None:
    """The backing-column read for a `JSONFieldAccess`, or None to leave it as the JSON extract.

    Picks the column and builds the read (the numeric/boolean cast is not handled here — it already wraps this node).
    Returns None when the property has no backing column or is access-restricted.
    """
    field_type = _blob_field_type_of(node)
    # Lowering builds every JSONFieldAccess with the blob FieldType on `expr` and a non-empty key path. Assert the
    # invariant rather than silently bailing, so a real violation fails loud instead of degrading to a JSON read.
    assert field_type is not None and node.keys

    first_key = str(node.keys[0])
    deeper_keys: list[str | int] = list(node.keys[1:])

    # Access control: a restricted property must not be read from its materialized column. Decline, so it stays a JSON
    # read — which the printer strips the restricted key from, collapsing the value to ''.
    if first_key in restricted_property_keys_for_table_type(field_type.table_type, context):
        return None

    source = resolve_materialized_property_source(field_type, first_key, context)
    if source is None:
        return None

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
    # Deeper keys read the column value as a JSON string. Emit a JSONFieldAccess rather than building the extract here:
    # the printer renders that node via `json_extract_trim_quotes` (kafka_engine.py), the one implementation of the
    # extract-and-trim SQL shape.
    return ast.JSONFieldAccess(expr=head, keys=deeper_keys, type=ast.StringType(nullable=True))


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
    """Rewrites lowered `JSONFieldAccess` reads (and comparisons over them) to read backing columns where they exist.

    After this pass, a backed property is an ordinary column expression; an unbacked (or restricted) one stays a
    `JSONFieldAccess` and prints as the raw JSON extract.
    """

    def __init__(self, context: HogQLContext) -> None:
        # The AST is printed directly after this pass, so keep resolved types rather than clearing them.
        super().__init__(clear_types=False)
        self.context = context
        # Per-SELECT map of column alias → its lowered property read, so a comparison that references the alias
        # (`SELECT properties.x AS a ... WHERE a = 'v'`) can find the property behind `a` and still be optimized.
        self._alias_scopes: list[dict[str, ast.JSONFieldAccess]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        scope: dict[str, ast.JSONFieldAccess] = {}
        for column in node.select or []:
            if isinstance(column, ast.Alias):
                inner = column.expr
                while isinstance(inner, ast.Alias):  # the resolver may nest a hidden alias under the user's `AS x`
                    inner = inner.expr
                if isinstance(inner, ast.JSONFieldAccess):
                    scope[column.alias] = inner
        self._alias_scopes.append(scope)
        try:
            return super().visit_select_query(node)
        finally:
            self._alias_scopes.pop()

    def _resolve_alias_to_property(self, expr: ast.Expr) -> ast.JSONFieldAccess | None:
        """A `Field` reference to a select-column alias over a lowered property read, resolved to that read, or None."""
        if not (isinstance(expr, ast.Field) and isinstance(expr.type, ast.FieldAliasType)):
            return None
        for scope in reversed(self._alias_scopes):
            resolved = scope.get(expr.type.alias)
            if resolved is not None:
                return resolved
        return None

    def _lowered_property_operand(self, expr: ast.Expr) -> ast.JSONFieldAccess | None:
        """The lowered `properties.$x` behind a comparison operand, or None.

        After lowering, such an operand is a `JSONFieldAccess` (often wrapped in an `Alias`). A bare `Field` that instead
        *references* a select-column alias over one (`... WHERE a = 'v'`) is looked up in the scope map.
        """
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        if isinstance(expr, ast.JSONFieldAccess):
            return expr
        return self._resolve_alias_to_property(expr)

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

        # Fallback for a property buried inside a cast: a boolean/numeric property gets wrapped by the swapper (e.g.
        # `toBool(transform(toString(...)))`) and aliased, so the `JSONFieldAccess` isn't the bare operand. Detect the
        # property from the operand's resolved `PropertyType` instead; the optimizer then drops the cast wrapper.
        prop_type = resolve_field_type(expr)
        if isinstance(prop_type, ast.PropertyType) and len(prop_type.chain) == 1:
            return prop_type.field_type, str(prop_type.chain[0])
        return None

    # --- value substitution ---

    def visit_jsonfield_access(self, node: ast.JSONFieldAccess) -> ast.Expr:
        substituted = _substitute_value_read(node, self.context)
        if substituted is not None:
            return substituted
        return super().visit_jsonfield_access(node)

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
        # surviving JSONFieldAccess reads the scrubbed materialized column. An is-set check therefore treats both an empty
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
        if source is None or source.kind not in ("materialized_column", "dmat"):
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
        if source is None or source.kind not in ("materialized_column", "dmat"):
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
        if prop is None or not isinstance(node.right, ast.Constant) or node.right.value is None:
            return None
        if self._is_ai_column(prop.source):
            return None

        cmp = _call(op_name, [prop.bare_column(), _const(node.right.value)])
        if prop.source.is_nullable:
            return _call("and", [cmp, prop.is_not_null()])
        # Non-nullable: exclude the '' / 'null' sentinels inline so the bare comparison stays index-eligible.
        clauses: list[ast.Expr] = [cmp]
        clauses.extend(_call("notEquals", [prop.bare_column(), _sentinel(s)]) for s in MAT_COL_NULL_SENTINELS)
        return _call("and", clauses)

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
    """Rewrite every backed lowered `JSONFieldAccess` (and comparison over it) to read its backing column.

    ClickHouse only. Expects a resolved, swapped, lowered AST, and runs right after `lower_property_access` in the
    ClickHouse print pipeline (see `prepare_ast_for_printing`).
    """
    return cast(_T_AST, ClickHousePropertyResolver(context).visit(node))
