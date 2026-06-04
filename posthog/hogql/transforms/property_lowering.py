from dataclasses import dataclass
from typing import Literal, cast

from posthog.schema import MaterializationMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.utils import ilike_matches, like_matches
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn

# In non-nullable materialized columns, these values are treated as NULL. Mirrors clickhouse.MAT_COL_NULL_SENTINELS.
MAT_COL_NULL_SENTINELS = ["", "null"]

# Columns whose null handling the ClickHouse printer optimizes itself (the $ai_* bloom-filter columns). Lowering must
# not intercept comparisons against these — it lowers them to the bare column and lets the printer's
# visit_compare_operation force `not_nullable=True`. Mirrors clickhouse.COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING.
COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING = {
    "mat_$ai_trace_id",
    "mat_$ai_session_id",
    "mat_$ai_is_error",
    "$ai_trace_id",
    "$ai_session_id",
    "$ai_is_error",
}

_RANGE_OP_TO_CH_NAME: dict[ast.CompareOperationOp, str] = {
    ast.CompareOperationOp.Lt: "less",
    ast.CompareOperationOp.LtEq: "lessOrEquals",
    ast.CompareOperationOp.Gt: "greater",
    ast.CompareOperationOp.GtEq: "greaterOrEquals",
}

# Properties whose materialized columns are deliberately read without the nullIf sentinel wrapping, so the
# bare column stays eligible for skip indexes. Mirrors BasePrinter.visit_property_type's special case.
AI_PROPERTIES_WITHOUT_NULLIF = {"$ai_trace_id", "$ai_session_id", "$ai_is_error"}


@dataclass(frozen=True)
class MaterializedPropertySource:
    """The single physical column the ClickHouse printer reads for an events/persons `properties.$x` access.

    This is the structured form of the printer's per-property decision (today encoded as the printable
    objects yielded by BasePrinter._get_all_materialized_property_sources). It is the shared source of truth
    for (a) the printer's lowering, (b) the property-lowering transform that turns a property into concrete
    column AST, and (c) the predicate-pushdown collector — so none of them can drift from the others.
    """

    kind: Literal["materialized_column", "dmat", "property_group"]
    column: str
    is_nullable: bool
    # Index metadata the ClickHouse comparison optimizations consult to keep the column index-eligible.
    has_minmax_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_index: bool = False
    has_bloom_filter_lower_index: bool = False


def resolve_materialized_property_source(
    field_type: ast.FieldType, property_name: str, context: HogQLContext
) -> MaterializedPropertySource | None:
    """The physical column the ClickHouse printer reads for `<events/persons>.<field>.<property_name>`, or None.

    Mirrors BasePrinter._get_all_materialized_property_sources' priority order — static materialized column,
    then dmat slot, then the first property-group Map column — using the same underlying registries, so the
    decision is computable before printing without instantiating a printer. Returns None when the property
    has no physical backing (the JSONExtract-over-the-blob fallback) or when materialization is disabled.
    """
    if context.modifiers.materializationMode == "disabled":
        return None

    table_type: ast.Type | None = field_type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
        table_type = table_type.table_type
    if not isinstance(table_type, ast.TableType):
        return None

    field = field_type.resolve_database_field(context)
    if not isinstance(field, DatabaseField):
        return None

    # The materialized-column registry is keyed by the ClickHouse table name, which differs from the HogQL name for
    # some tables (RawPersonsTable prints "raw_persons" in HogQL but "person" in ClickHouse). Use the same name the
    # ClickHouse printer's `_get_table_name` override uses, or person-joined materialized properties silently fall
    # back to a JSON read (and lose the empty-string→NULL scrubbing that the materialized column provides).
    table_name = table_type.table.to_printed_clickhouse(context)
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
    if context.modifiers.propertyGroupsMode in (PropertyGroupsMode.ENABLED, PropertyGroupsMode.OPTIMIZED):
        for group_column in property_groups.get_property_group_columns(table_name, field_name, property_name):
            return MaterializedPropertySource(kind="property_group", column=group_column, is_nullable=True)

    return None


def lower_property_type(property_type: ast.PropertyType, context: HogQLContext) -> ast.Expr | None:
    """Concrete column AST equivalent to what the ClickHouse printer + property swapper emit for `properties.$x`.

    Returns the lowered expression — a bare/`nullIf`-wrapped materialized column, a property-group map access,
    or a `JSONExtract` over the raw blob — wrapped in the registered scalar cast (`toFloat`/`toDateTime`/
    `toBool`) for single-key event/person properties, built only from registered HogQL functions so it survives
    printing. Returns ``None`` when the access can't be safely lowered here (already repointed into a joined
    subquery, property-level access control in play, or an unusual table wrapper); the caller leaves the
    original ``PropertyType`` in place for the printer.

    Column selection mirrors `BasePrinter.visit_property_type`; the cast mirrors
    `PropertySwapper._field_type_to_property_call`. This pass runs *before* the swapper, so it owns the cast for
    the properties it lowers and the swapper no-ops on them (it only sees the un-lowered tail it still handles).

    Equivalence bar is **result-equivalence, not byte-identical**: the printer string-builds the property-group
    read as a `? :` ternary and the JSON read with literal (non-parameterized) constants, neither of which any
    AST node reproduces. The lowered form (`if(has(g,k), g[k], null)`, parameterized constants) prints
    differently but evaluates identically.
    """
    # Already repointed into a joined subquery: the printer reads it as a plain aliased column.
    if property_type.joined_subquery is not None:
        return None

    chain = property_type.chain
    if not chain:
        return None

    base_field_type = property_type.field_type

    # Only lower accesses on a JSON blob column (`properties` / `person_properties`). Struct and array fields (e.g.
    # data-warehouse tables) have their own printer handling (tupleElement, array indexing) and must not be
    # JSON-extracted. A materialized column is only ever built for a plain physical table; non-physical wrappers
    # (column-aliased tables, subquery columns) resolve no source below and fall through to the JSON-blob read.
    if not isinstance(base_field_type.resolve_database_field(context), StringJSONDatabaseField):
        return None

    # The first chain element is always a top-level property name (a string). Deeper elements keep their original
    # Python type: integers are array indices that JSONExtractRaw must receive as integers (the string '1' would
    # look up object key "1", not array element 1; the printer passes them through untyped for the same reason).
    first_key = str(chain[0])
    deeper_keys: list[str | int] = [link if isinstance(link, int) else str(link) for link in chain[1:]]

    # Property-level access control: a restricted property must not be read from its materialized column (that
    # column holds the real value, unscrubbable). Force the JSON-blob read instead — the printer's visit_field_type
    # wraps that blob in JSONDropKeys, collapsing the value to ''. Uses the same restriction check the printer does
    # (restricted_property_keys_for_table_type), so the two can't drift.
    restricted_keys = restricted_property_keys_for_table_type(base_field_type.table_type, context)
    source = (
        None if first_key in restricted_keys else resolve_materialized_property_source(base_field_type, first_key, context)
    )

    if source is None:
        # No physical backing: JSONExtractRaw over the raw blob for the full chain.
        lowered: ast.Expr = _json_extract_trim_quotes_expr(_blob_field(base_field_type), [first_key, *deeper_keys])
    else:
        head = _materialized_head_expr(source, base_field_type, first_key, is_single=not deeper_keys, context=context)
        if head is None:
            return None
        # Deeper keys read the materialized value as a JSON string, same as the printer's chain[1:] handling.
        lowered = head if not deeper_keys else _json_extract_trim_quotes_expr(head, deeper_keys)

    # Scalar cast — only single-key event/person properties get coerced (mirrors the swapper's chain[0]-only rule).
    if not deeper_keys:
        cast_type = _property_cast_type(property_type, context)
        if cast_type is not None:
            lowered = _apply_property_cast(lowered, cast_type)
    return lowered


def _property_cast_type(property_type: ast.PropertyType, context: HogQLContext) -> str | None:
    """The registered scalar type the PropertySwapper would coerce this property to, or None.

    Mirrors `PropertySwapper.visit_field`'s single-key event/person coercion. Group properties (resolved via
    lazy joins, then repointed into a subquery) don't reach here as raw `PropertyType`s, so they stay with the
    swapper. Returns one of "Float" / "DateTime" / "Boolean" / "String", or None when the property isn't in the
    resolved registry (i.e. the swapper would leave it as a raw string).
    """
    swapper = context.property_swapper
    if swapper is None or len(property_type.chain) != 1:
        return None

    base_field_type = property_type.field_type
    property_name = str(property_type.chain[0])
    field_name = base_field_type.name
    raw_table_type = base_field_type.table_type

    prop_info: dict[str, str | None] | None = None
    # PoE person properties read `properties.$x` off the events person sub-table (a VirtualTableType).
    if isinstance(raw_table_type, ast.VirtualTableType) and raw_table_type.field == "poe":
        if field_name == "properties":
            prop_info = swapper.person_properties.get(property_name)
    elif field_name == "person_properties":
        prop_info = swapper.person_properties.get(property_name)
    elif field_name == "properties":
        table_type = _underlying_table_type(raw_table_type)
        if table_type is None:
            return None
        table = table_type.table
        if isinstance(table, (PersonsTable, RawPersonsTable, EventsPersonSubTable)):
            prop_info = swapper.person_properties.get(property_name)
        elif isinstance(table, EventsTable):
            prop_info = swapper.event_properties.get(property_name)

    if not prop_info:
        return None
    return "Float" if prop_info.get("type") == "Numeric" else (prop_info.get("type") or "String")


def _apply_property_cast(expr: ast.Expr, field_type: str) -> ast.Expr:
    """Wrap a lowered property value in its scalar cast. Mirrors PropertySwapper._field_type_to_property_call."""
    if field_type == "DateTime":
        # Carry the return type so an enclosing toDateTime() resolves its already-a-datetime overload.
        return ast.Call(
            name="toDateTime",
            args=[expr],
            type=ast.CallType(
                name="toDateTime",
                arg_types=[ast.StringType(nullable=True)],
                return_type=ast.DateTimeType(nullable=True),
            ),
        )
    if field_type == "Float":
        return ast.Call(name="toFloat", args=[expr])
    if field_type == "Boolean":
        return ast.Call(
            name="toBool",
            args=[
                ast.Call(
                    name="transform",
                    args=[
                        ast.Call(name="toString", args=[expr]),
                        ast.Constant(value=["true", "false"]),
                        ast.Constant(value=[1, 0]),
                        ast.Constant(value=None),
                    ],
                )
            ],
        )
    return expr


def _materialized_head_expr(
    source: MaterializedPropertySource,
    base_field_type: ast.FieldType,
    first_key: str,
    *,
    is_single: bool,
    context: HogQLContext,
) -> ast.Expr | None:
    """The chain[0] read for a materialized source — mirrors the branches in BasePrinter.visit_property_type."""
    unqualified = context.within_non_hogql_query
    if source.kind == "property_group":
        # `has(g, k) ? g[k] : null` — guard the map read so a missing key returns NULL, not the '' map default.
        has_field = _synthetic_column_field(base_field_type, source.column, is_nullable=True, unqualified=unqualified)
        get_field = _synthetic_column_field(base_field_type, source.column, is_nullable=True, unqualified=unqualified)
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

    column_field = _synthetic_column_field(
        base_field_type, source.column, is_nullable=source.is_nullable, unqualified=unqualified
    )
    if column_field is None:
        return None

    # Nullable columns (dmat, nullable mat) and the index-friendly $ai single-key columns are read bare.
    if source.is_nullable or (is_single and first_key in AI_PROPERTIES_WITHOUT_NULLIF):
        return column_field

    # Non-nullable materialized column: scrub the '' / 'null' string sentinels back to NULL.
    scrubbed_empty = ast.Call(name="nullIf", args=[column_field, _sentinel("")])
    if context.modifiers.materializationMode == MaterializationMode.LEGACY_NULL_AS_STRING:
        return scrubbed_empty
    return ast.Call(name="nullIf", args=[scrubbed_empty, _sentinel("null")])


def _sentinel(value: str) -> ast.Constant:
    """A fixed, known-safe literal string the ClickHouse printer renders inline (not parameterized).

    Used only for the materialization sentinels ('' / 'null' / the trim regex), so the lowered SQL matches the
    printer's hand-built strings byte-for-byte. Property keys stay parameterized via plain ast.Constant.
    """
    return ast.Constant(value=value, inline=True)


def _json_extract_trim_quotes_expr(field_expr: ast.Expr, keys: list[str | int]) -> ast.Expr:
    """AST form of clickhouse.kafka_engine.json_extract_trim_quotes(field, *keys).

    Integer keys (array indices) are emitted as integer constants so JSONExtractRaw indexes the array; string keys
    are object lookups. This mirrors the printer passing the raw chain values through untyped.
    """
    extract = ast.Call(
        name="JSONExtractRaw",
        args=[field_expr, *[ast.Constant(value=key) for key in keys]],
    )
    scrubbed = ast.Call(
        name="nullIf",
        args=[
            ast.Call(name="nullIf", args=[extract, _sentinel("")]),
            _sentinel("null"),
        ],
    )
    return ast.Call(name="replaceRegexpAll", args=[scrubbed, _sentinel('^"|"$'), _sentinel("")])


def _blob_field(base_field_type: ast.FieldType) -> ast.Field:
    """A Field over the raw JSON blob column (`properties` / `person_properties`), reusing its resolved type."""
    return ast.Field(chain=[base_field_type.name], type=base_field_type)


def _synthetic_column_field(
    base_field_type: ast.FieldType, column_name: str, *, is_nullable: bool, unqualified: bool = False
) -> ast.Field | None:
    """A typed Field for a physical ClickHouse column that isn't a HogQL schema field.

    Mat/dmat/property-group columns live on the table physically but aren't in the HogQL schema, so a plain
    Field won't resolve. Synthesize a DatabaseField on a copy of the table and point a fresh FieldType at it,
    preserving any alias wrapper so the printed table prefix (`events.` / `e.`) is unchanged. Mirrors the
    pushdown transform's `_inner_table_type_with_materialized_columns`.

    `unqualified=True` (set for `within_non_hogql_query` fragments) makes the printer drop the table prefix —
    those fragments splice into a fixed-scope statement (e.g. a lightweight DELETE) that rejects `events.mat_x`.
    """
    table_type = _augment_table_type(base_field_type.table_type, column_name, is_nullable=is_nullable)
    if table_type is None:
        return None
    return ast.Field(
        chain=[column_name], type=ast.FieldType(name=column_name, table_type=table_type, unqualified=unqualified)
    )


def _augment_table_type(
    table_type: ast.Type, column_name: str, *, is_nullable: bool
) -> ast.TableType | ast.TableAliasType | None:
    if isinstance(table_type, ast.VirtualTableType):
        # PoE person properties: the physical mat/group columns live on the underlying events table.
        return _augment_table_type(table_type.table_type, column_name, is_nullable=is_nullable)
    if isinstance(table_type, ast.TableAliasType):
        inner = table_type.table_type
        if not isinstance(inner, ast.TableType):
            return None
        return ast.TableAliasType(
            alias=table_type.alias, table_type=_augment_plain_table_type(inner, column_name, is_nullable)
        )
    if isinstance(table_type, ast.TableType):
        return _augment_plain_table_type(table_type, column_name, is_nullable)
    return None


def _augment_plain_table_type(table_type: ast.TableType, column_name: str, is_nullable: bool) -> ast.TableType:
    table = table_type.table
    if table.has_field(column_name):
        return table_type
    synthetic = DatabaseField(name=column_name, nullable=is_nullable)
    augmented = table.model_copy(update={"fields": {**table.fields, column_name: synthetic}})
    return ast.TableType(table=augmented)


def _underlying_table_type(table_type: ast.Type) -> ast.TableType | None:
    while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
        table_type = table_type.table_type
    if isinstance(table_type, ast.TableType):
        return table_type
    return None


# --- Optimized comparison forms: reproduce the ClickHouse printer's skip-index-friendly rewrites as AST. ---
#
# These mirror ClickHousePrinter._get_optimized_* (see posthog/hogql/printer/clickhouse.py). The printer detects a
# PropertyType operand and rewrites the comparison so the bare materialized column / property-group map access stays
# eligible for ClickHouse skip indexes (minmax / bloom filter / ngram). Lowering runs *before* the swapper and removes
# the PropertyType, so the printer optimizers stop firing — we reproduce the optimized form here, consuming the
# property, so the skip-index forms survive. Functionality (results + index eligibility), not byte-exact SQL, is the
# bar; we use only registered HogQL functions and parameterized constants (the printer string-builds some of these).


def _call(name: str, args: list[ast.Expr]) -> ast.Call:
    return ast.Call(name=name, args=args)


def _lower(expr: ast.Expr) -> ast.Call:
    """`lower(expr)`, typed non-nullable String so the printer doesn't ifNull-wrap a comparison against it."""
    return ast.Call(name="lower", args=[expr], type=ast.StringType(nullable=False))


def _coalesce_empty(expr: ast.Expr) -> ast.Call:
    """`coalesce(expr, '')`, typed non-nullable String — matches the lower-index expression and prints bare."""
    return ast.Call(name="coalesce", args=[expr, _sentinel("")], type=ast.StringType(nullable=False))


def _const(value: object) -> ast.Constant:
    return ast.Constant(value=value)


def _is_null_constant(expr: ast.Expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def _resolve_field_type(expr: ast.Expr) -> ast.Type | None:
    """An operand's resolved type, unwrapping field-alias wrappers. Mirrors printer.resolve_field_type."""
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    return expr_type


def _resolve_property_type(expr: ast.Expr) -> ast.PropertyType | None:
    """The PropertyType an operand resolves to, unwrapping field-alias types. Mirrors printer.resolve_field_type."""
    expr_type = _resolve_field_type(expr)
    return expr_type if isinstance(expr_type, ast.PropertyType) else None


def _and_all(clauses: list[ast.Expr]) -> ast.Expr:
    """`and(...)` over the clauses (single clause returned bare). The printer renders chained `AND`; result-equivalent."""
    if len(clauses) == 1:
        return clauses[0]
    return _call("and", clauses)


@dataclass(frozen=True)
class _OptimizableProperty:
    """A single-key materializable property operand of a comparison, paired with its resolved physical source."""

    property_type: ast.PropertyType
    field_type: ast.FieldType
    key: str
    source: MaterializedPropertySource
    # Print the synthetic columns unqualified (within_non_hogql_query fragments). See _synthetic_column_field.
    unqualified: bool = False


def _group_map_field(prop: _OptimizableProperty) -> ast.Field:
    """The property-group `Map(String, String)` column, read non-nullable so map access / has() print bare.

    The map column itself is non-nullable; a missing key yields the type default (''), not SQL NULL. Marking the
    synthetic field non-nullable keeps the printer from ifNull-wrapping `equals(g[k], v)` (which would defeat the
    bloom-filter index) — matching what PrintableMaterializedPropertyGroupItem prints.
    """
    field = _synthetic_column_field(prop.field_type, prop.source.column, is_nullable=False, unqualified=prop.unqualified)
    assert field is not None  # the source was resolved from this same field_type
    return field


def _group_has_expr(prop: _OptimizableProperty) -> ast.Call:
    """`has(group_map_column, key)` — mirrors PrintableMaterializedPropertyGroupItem.has_expr."""
    return _call("has", [_group_map_field(prop), _const(prop.key)])


def _group_value_expr(prop: _OptimizableProperty) -> ast.ArrayAccess:
    """`group_map_column[key]` — mirrors PrintableMaterializedPropertyGroupItem.value_expr.

    Typed as a non-nullable String: map access over `Map(String, String)` returns the (non-nullable) value type,
    a missing key yielding the '' default. The explicit type stops the printer from ifNull-wrapping
    `equals(g[k], v)`, which would otherwise defeat the values bloom-filter index.
    """
    return ast.ArrayAccess(array=_group_map_field(prop), property=_const(prop.key), type=ast.StringType(nullable=False))


def _bare_mat_column(prop: _OptimizableProperty) -> ast.Field:
    """The materialized column read bare (no nullIf scrubbing), typed non-nullable.

    Typed non-nullable so the printer's `visit_compare_operation` sees `not_nullable` and does NOT wrap the
    comparison in `ifNull(..., 0)` — the very wrapping that hides the column from skip indexes. The real ClickHouse
    column may be `Nullable`; nullability is handled explicitly by the optimizer (an `isNotNull(col)` guard or an
    `ifNull(...)` around the whole result), exactly as the printer's string-built optimized forms do.
    """
    field = _synthetic_column_field(prop.field_type, prop.source.column, is_nullable=False, unqualified=prop.unqualified)
    assert field is not None
    return field


def _is_not_null(prop: _OptimizableProperty) -> ast.Call:
    """`isNotNull(col)` over a *nullable* view of the column — result-equivalent to the printer's `col IS NOT NULL`.

    A nullable-typed field is needed here so the printer keeps the guard (rather than treating it as trivially true).
    """
    field = _synthetic_column_field(prop.field_type, prop.source.column, is_nullable=True, unqualified=prop.unqualified)
    assert field is not None
    return _call("isNotNull", [field])


def _string_pattern_constant(expr: ast.Expr) -> ast.Constant | None:
    return expr if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


class LowerProperties(CloningVisitor):
    """Replaces `properties.$x` Field accesses with the concrete column AST the printer would emit.

    Runs on a resolved ClickHouse AST. After this pass, the lowered accesses are ordinary typed column
    expressions (no `PropertyType`), so downstream transforms — notably the events-predicate pushdown — can
    project and repoint them like any other column.
    """

    def __init__(self, context: HogQLContext):
        # Keep resolved types — the lowered AST is printed directly, no re-resolution runs after this pass.
        super().__init__(clear_types=False)
        self.context = context

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if isinstance(node.type, ast.PropertyType):
            lowered = lower_property_type(node.type, self.context)
            if lowered is not None:
                return lowered
        return super().visit_field(node)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        # `isNull`/`isNotNull`/`JSONHas` on a property group property can read the keys-only `has(g, k)` instead of
        # the values subcolumn — and stays eligible for the keys bloom-filter index. Mirrors
        # ClickHousePrinter._get_optimized_property_group_call.
        optimized = self._optimize_property_group_call(node)
        if optimized is not None:
            return optimized

        # Comparison functions written in call form (`equals(properties.x, v)`, `ilike(toString(properties.x), p)`,
        # `in(properties.x, (...))`) are comparisons in disguise — the printer routes them through
        # visit_compare_operation. Do the same so the same skip-index optimizers fire (otherwise we'd recurse into the
        # args and lower the property, defeating the optimization). Only the plain 2-arg form, no params.
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
        # Reproduce the ClickHouse printer's skip-index comparison optimizers as AST, in the printer's dispatch order
        # (clickhouse.visit_compare_operation). Each consumes the property operand and returns the optimized form, so
        # we must NOT also lower the property. Session-id is intentionally left to the printer (see report).
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

        # `property = NULL` / `property != NULL` (is-set / is-not-set) on a *non-group* property: the printer needs the
        # PropertyType to apply its is-set semantics — a non-nullable materialized column stores '' for both
        # empty-string and missing, so it can't detect "not set" and the printer falls back to JSONHas on the blob.
        # Leaving the operand un-lowered preserves that exact behavior. (Group `= NULL` is handled by the group
        # optimizer above, which rewrites it to `has`/`not(has)`.)
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq) and (
            _is_null_constant(node.left) or _is_null_constant(node.right)
        ):
            return clone_expr(node, clear_types=False)
        return super().visit_compare_operation(node)

    # --- property operand detection (mirrors ClickHousePrinter._get_materialized_string_property_source) ---

    def _materialized_string_property(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key string property access backed by an individually materialized column, or None.

        Mirrors ClickHousePrinter._get_materialized_string_property_source: unwraps a `toString(properties.x)` safety
        wrapper, requires a single-key chain, skips properties with a non-string resolved type, and requires the
        property to back a `materialized_column` (not a property group). Lowering runs before the swapper, so the
        operand is a clean `PropertyType` — there is no `toFloat`/`accurateCastOrNull` wrapper to confuse us, but we
        still honor the `toString(...)` unwrap for parity with user-written queries.
        """
        property_type = _resolve_property_type(expr)
        if property_type is None and isinstance(expr, ast.Call) and expr.name == "toString" and len(expr.args) == 1:
            inner = expr.args[0]
            if isinstance(inner, ast.Alias):
                inner = inner.expr
            if isinstance(inner, ast.Field):
                inner_type = _resolve_property_type(inner)
                if inner_type is not None and len(inner_type.chain) == 1:
                    property_type = inner_type
        if property_type is None or len(property_type.chain) != 1:
            return None

        property_name = str(property_type.chain[0])
        if self.context.property_swapper is not None:
            prop_info = self.context.property_swapper.event_properties.get(property_name)
            if prop_info is not None and prop_info.get("type") not in (None, "String"):
                return None

        source = resolve_materialized_property_source(property_type.field_type, property_name, self.context)
        if source is None or source.kind not in ("materialized_column", "dmat"):
            return None
        return _OptimizableProperty(
            property_type,
            property_type.field_type,
            property_name,
            source,
            unqualified=self.context.within_non_hogql_query,
        )

    def _materialized_property_for_op(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key materialized-column property (any resolved type), for IN comparisons that don't need a string."""
        property_type = _resolve_property_type(expr)
        if property_type is None or len(property_type.chain) != 1:
            return None
        property_name = str(property_type.chain[0])
        source = resolve_materialized_property_source(property_type.field_type, property_name, self.context)
        if source is None or source.kind not in ("materialized_column", "dmat"):
            return None
        return _OptimizableProperty(
            property_type,
            property_type.field_type,
            property_name,
            source,
            unqualified=self.context.within_non_hogql_query,
        )

    def _property_group_property(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key property backed by a property group, only under OPTIMIZED mode."""
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None
        property_type = _resolve_property_type(expr)
        if property_type is None or len(property_type.chain) > 1:
            return None
        property_name = str(property_type.chain[0])
        source = resolve_materialized_property_source(property_type.field_type, property_name, self.context)
        if source is None or source.kind != "property_group":
            return None
        return _OptimizableProperty(
            property_type,
            property_type.field_type,
            property_name,
            source,
            unqualified=self.context.within_non_hogql_query,
        )

    @staticmethod
    def _is_ai_column(source: MaterializedPropertySource) -> bool:
        return source.column.strip("`\"'") in COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING

    # --- property-group optimizers (mirror _get_optimized_property_group_compare_operation / _call) ---

    def _optimize_property_group_call(self, node: ast.Call) -> ast.Expr | None:
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        if node.name in ("isNull", "isNotNull") and len(node.args) == 1:
            prop = self._property_group_property(node.args[0])
            if prop is None:
                return None
            has_expr = _group_has_expr(prop)
            return _call("not", [has_expr]) if node.name == "isNull" else has_expr

        if node.name == "JSONHas" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            prop = self._property_group_property(node.args[0])
            if prop is None:
                return None
            # The key on JSONHas is the literal; resolve the group source for that key off the blob field.
            key = str(node.args[1].value)
            field_type = _resolve_field_type(node.args[0])
            if not isinstance(field_type, ast.FieldType):
                return None
            source = resolve_materialized_property_source(field_type, key, self.context)
            if source is None or source.kind != "property_group":
                return None
            return _group_has_expr(
                _OptimizableProperty(
                    prop.property_type, field_type, key, source, unqualified=self.context.within_non_hogql_query
                )
            )

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
                # `= NULL` ⇒ key absent: `not(has(g, k))`. Avoids reading the values subcolumn.
                return _call("not", [_group_has_expr(prop)])
            if value is True:
                # 'true'/'false' are fixed, known-safe literals (the stored boolean encoding) — render inline like the
                # printer so the values bloom-filter index expression matches.
                return _call("equals", [_group_value_expr(prop), _sentinel("true")])
            if value is False:
                return _call("equals", [_group_value_expr(prop), _sentinel("false")])
            if isinstance(constant_expr.type, ast.StringType):
                eq = _call("equals", [_group_value_expr(prop), _const(value)])
                if value == "":
                    # Disambiguate from the Map default ('') by also checking the key is present.
                    return _call("and", [_group_has_expr(prop), eq])
                return eq
            return None

        # NotEq
        if value is None:
            # `!= NULL` ⇒ key present: `has(g, k)`. Uses the keys index, skips the values subcolumn.
            return _group_has_expr(prop)
        return None

    def _optimize_property_group_in(self, node: ast.CompareOperation) -> ast.Expr | None:
        # IN is not commutative; only the left operand can be the property.
        prop = self._property_group_property(node.left)
        if prop is None:
            return None

        if isinstance(node.right, ast.Constant):
            value = node.right.value
            if value is None:
                return None  # unoptimized IN(NULL) is true if key absent OR value null; can't shortcut
            if value == "":
                return _call("and", [_group_has_expr(prop), _call("equals", [_group_value_expr(prop), _const("")])])
            if isinstance(node.right.type, ast.StringType):
                return _call("equals", [_group_value_expr(prop), _const(value)])
            return None
        if isinstance(node.right, (ast.Tuple, ast.Array)):
            return self._optimize_group_in_with_values(node.right.exprs, prop)
        return None

    def _optimize_group_in_with_values(self, values: list[ast.Expr], prop: _OptimizableProperty) -> ast.Expr | None:
        # Mirror ClickHousePrinter._optimize_in_with_string_values: bail on any non-string / empty / NULL value.
        string_values: list[str] = []
        for v in values:
            if not isinstance(v, ast.Constant) or v.value == "" or v.value is None or not isinstance(v.value, str):
                return None
            string_values.append(v.value)
        if len(string_values) == 0:
            return _const(False)  # IN () is always false
        if len(string_values) == 1:
            return _call("equals", [_group_value_expr(prop), _const(string_values[0])])
        # transform_null_in=1 makes `in(g[k], ...)` skip the keys index; the `has` guard restores it.
        in_expr = _call("in", [_group_value_expr(prop), ast.Tuple(exprs=[_const(v) for v in string_values])])
        return _call("and", [_group_has_expr(prop), in_expr])

    # --- individually-materialized-column optimizers (mirror _get_optimized_materialized_column_*) ---

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
            return None  # let the normal nullIf path handle sentinel comparisons
        if self._is_ai_column(prop.source):
            return None  # printer optimizes these

        column = _bare_mat_column(prop)
        value = _const(constant_expr.value)
        if node.op == ast.CompareOperationOp.Eq:
            eq = _call("equals", [column, value])
            if prop.source.is_nullable:
                return _call("and", [eq, _is_not_null(prop)])
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
        # property_to_expr always emits the column on the left, so only that side is handled.
        prop = self._materialized_string_property(node.left)
        if prop is None or not isinstance(node.right, ast.Constant) or node.right.value is None:
            return None
        if self._is_ai_column(prop.source):
            return None

        cmp = _call(op_name, [_bare_mat_column(prop), _const(node.right.value)])
        if prop.source.is_nullable:
            return _call("and", [cmp, _is_not_null(prop)])
        # Non-nullable: exclude the '' / 'null' sentinels inline so the bare comparison stays index-eligible.
        clauses: list[ast.Expr] = [cmp]
        clauses.extend(_call("notEquals", [_bare_mat_column(prop), _sentinel(s)]) for s in MAT_COL_NULL_SENTINELS)
        return _and_all(clauses)

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
                    indexed = _lower(_coalesce_empty(_bare_mat_column(prop)))
                    return _call(
                        "and",
                        [_call("like", [indexed, _lower(_const(pattern.value))]), _is_not_null(prop)],
                    )
                return _call(
                    "and", [_call("ilike", [_bare_mat_column(prop), _const(pattern.value)]), _is_not_null(prop)]
                )
            return _call("ifNull", [_call("notILike", [_bare_mat_column(prop), _const(pattern.value)]), _const(True)])

        # Non-nullable: bail if the pattern could match a stored sentinel.
        if any(ilike_matches(cast(str, pattern.value), s) for s in MAT_COL_NULL_SENTINELS):
            return None
        if is_ilike:
            if prop.source.has_ngram_lower_index:
                return _call("like", [_lower(_bare_mat_column(prop)), _lower(_const(pattern.value))])
            return _call("ilike", [_bare_mat_column(prop), _const(pattern.value)])
        return _call("notILike", [_bare_mat_column(prop), _const(pattern.value)])

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
                return _call(
                    "and", [_call("like", [_bare_mat_column(prop), _const(pattern.value)]), _is_not_null(prop)]
                )
            return _call("ifNull", [_call("notLike", [_bare_mat_column(prop), _const(pattern.value)]), _const(True)])

        if any(like_matches(cast(str, pattern.value), s) for s in MAT_COL_NULL_SENTINELS):
            return None
        if is_like:
            return _call("like", [_bare_mat_column(prop), _const(pattern.value)])
        return _call("notLike", [_bare_mat_column(prop), _const(pattern.value)])

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
                # transform_null_in=1 makes in() hard to index; flip to has([...], col) (safe: NULL already excluded).
                array = ast.Array(exprs=[_const(v) for v in values])
                return _call("and", [_call("has", [array, _bare_mat_column(prop)]), _is_not_null(prop)])
            tup = ast.Tuple(exprs=[_const(v) for v in values])
            return _call("ifNull", [_call("notIn", [_bare_mat_column(prop), tup]), _const(True)])

        # non-nullable: bail if any value is a stored sentinel.
        if any(v in MAT_COL_NULL_SENTINELS for v in values):
            return None
        if node.op == ast.CompareOperationOp.In:
            array = ast.Array(exprs=[_const(v) for v in values])
            return _call("has", [array, _bare_mat_column(prop)])
        tup = ast.Tuple(exprs=[_const(v) for v in values])
        return _call("notIn", [_bare_mat_column(prop), tup])

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
            indexed: ast.Expr = _lower(_coalesce_empty(_bare_mat_column(prop)))
        else:
            indexed = _lower(_bare_mat_column(prop))

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


def lower_properties(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Lower every materializable `properties.$x` access in a resolved ClickHouse AST to concrete column AST.

    Runs for every ClickHouse query. For `within_non_hogql_query` fragments the synthetic physical-column fields
    are marked `unqualified` so the printer drops the table prefix (those fragments splice into a fixed-scope
    statement, e.g. a lightweight DELETE, that rejects table-qualified columns).
    """
    return cast(_T_AST, LowerProperties(context).visit(node))
