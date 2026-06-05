"""ClickHouse physical optimization passes for the printer rearchitecture (see PRINTER_REARCHITECTURE.md §4.5, §12.3).

Input: a resolved ClickHouse AST in which JSON-blob property *value* reads are the dialect-neutral `JSONFieldAccess`
logical leaf (produced by `logical_property_lowering.lower_property_access`, run *after* `PropertySwapper`, so a
registered property is e.g. `toFloat(JSONFieldAccess(...))` — the cast wraps the node). Output: the same AST with each
`JSONFieldAccess` over an events/persons `properties`/`person_properties` blob rewritten to its physical ClickHouse form
when one exists — the scrubbed materialized column, a dmat column, or a property-group map access — and comparisons over
such a node rewritten to the bare-column, skip-index-friendly shapes. A `JSONFieldAccess` with no physical backing (or a
restricted property) is left untouched: the base ClickHouse printer renders it as the raw-blob `JSONExtractRaw` read,
which for a restricted property is `JSONDropKeys`-wrapped (value collapses to `''`) exactly as on master.

This is **ClickHouse-only** and runs nowhere in the pipeline yet (built + unit-tested in isolation this round, doc
§12.3). It emits ClickHouse-specific AST (`nullIf` scrubbing, `Map` access, skip-index forms) — it must never run for the
warehouse dialects (doc §8.12).

Two parts, mirroring the printer's two property surfaces on master:

1. **Materialized-column value substitution** (`visit_jsonfield_access`) — reproduces `BasePrinter.visit_property_type`'s
   column selection + scrubbing. NOT the scalar cast: that already wraps the node (the swapper applied it before lowering).
2. **Skip-index comparison rewrites** (`visit_compare_operation` / `visit_call`) — reproduces
   `ClickHousePrinter`'s 8 `_get_optimized_*` forms + the property-group eq/in/JSONHas/isNull forms under
   `PropertyGroupsMode.OPTIMIZED`. `$session_id` is left to the printer for now (it optimizes a real column, not a
   property — doc §4.5).

Equivalence bar is **result-equivalence, not byte-identical** (doc §8.7): the printer string-builds `? :` ternaries and
inline literal constants no AST reproduces; the lowered AST prints differently but executes identically and keeps the
same skip-index eligibility. Verification is by execution + skip-index `EXPLAIN`, never SQL text.

§12.7 / §8.2 known quirk (preserved): is-set (`IS NULL` / `= NULL`) over a *materialized* property substitutes the value
read even under `isNull(...)`, so it over-matches empty-string and the literal `"null"` string exactly as master does.
This is deliberate (`# KNOWN:` below); the truthful blob key-existence fix is deferred to a separate signed-off change.
"""

from dataclasses import dataclass
from typing import Literal, cast

from posthog.schema import MaterializationMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, StringJSONDatabaseField
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.utils import ilike_matches, like_matches
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn

# In non-nullable materialized columns these stored strings are treated as NULL. Mirrors clickhouse.MAT_COL_NULL_SENTINELS.
MAT_COL_NULL_SENTINELS = ["", "null"]

# Columns whose null handling the ClickHouse printer optimizes itself (the $ai_* bloom-filter columns). The comparison
# rewrites must not intercept these — the printer's visit_compare_operation forces `not_nullable=True` for them. Mirrors
# clickhouse.COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING.
COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING = {
    "mat_$ai_trace_id",
    "mat_$ai_session_id",
    "mat_$ai_is_error",
    "$ai_trace_id",
    "$ai_session_id",
    "$ai_is_error",
}

# Properties whose materialized columns are read without the nullIf sentinel wrapping, so the bare column stays eligible
# for skip indexes. Mirrors the special case in BasePrinter.visit_property_type.
AI_PROPERTIES_WITHOUT_NULLIF = {"$ai_trace_id", "$ai_session_id", "$ai_is_error"}

_RANGE_OP_TO_CH_NAME: dict[ast.CompareOperationOp, str] = {
    ast.CompareOperationOp.Lt: "less",
    ast.CompareOperationOp.LtEq: "lessOrEquals",
    ast.CompareOperationOp.Gt: "greater",
    ast.CompareOperationOp.GtEq: "greaterOrEquals",
}


@dataclass(frozen=True)
class MaterializedPropertySource:
    """The single physical column the ClickHouse printer reads for an events/persons `properties.$x` access.

    Structured form of the printer's per-property decision (today encoded as the printable objects yielded by
    `BasePrinter._get_all_materialized_property_sources`).
    """

    kind: Literal["materialized_column", "dmat", "property_group"]
    column: str
    is_nullable: bool
    # Index metadata the comparison optimizations consult to keep the column index-eligible.
    has_minmax_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_index: bool = False
    has_bloom_filter_lower_index: bool = False


def resolve_materialized_property_source(
    field_type: ast.FieldType, property_name: str, context: HogQLContext
) -> MaterializedPropertySource | None:
    """The physical column the ClickHouse printer reads for `<events/persons>.<field>.<property_name>`, or None.

    Mirrors `BasePrinter._get_all_materialized_property_sources`' priority order — static materialized column, then dmat
    slot, then the first property-group Map column — using the same registries, so the decision is computable without
    instantiating a printer. Returns None when the property has no physical backing (JSON-blob fallback) or when
    materialization is disabled.
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

    # §8.1: the materialized-column registry is keyed by the ClickHouse table name, which differs from the HogQL name for
    # some tables (RawPersonsTable prints "raw_persons" in HogQL but "person" in ClickHouse). Use the same name the
    # ClickHouse printer's `_get_table_name` override uses, or person-joined materialized properties silently fall back to
    # a JSON read (and lose the empty-string→NULL scrubbing the materialized column provides).
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
    return resolve_property_group_source(field_type, property_name, context)


def resolve_property_group_source(
    field_type: ast.FieldType, property_name: str, context: HogQLContext
) -> MaterializedPropertySource | None:
    """The first property-group Map column for `<events/persons>.<field>.<property_name>`, ignoring materialized columns.

    Mirrors the deleted `ClickHousePrinter._get_property_group_source_for_field`: key existence (`JSONHas`) is answered
    from the property group's keys bloom-filter index even when an individually materialized column also exists, since
    that column can't answer key-existence (it stores '' for both "absent" and "empty"). The mat-column-first
    `resolve_materialized_property_source` would shadow the group, so JSONHas must resolve the group directly.
    """
    if context.modifiers.propertyGroupsMode not in (PropertyGroupsMode.ENABLED, PropertyGroupsMode.OPTIMIZED):
        return None

    table_type: ast.Type | None = field_type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
        table_type = table_type.table_type
    if not isinstance(table_type, ast.TableType):
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
# §4.4: a `JSONFieldAccess` carries its *value* type (a nullable String), NOT the original `PropertyType`. Everything the
# physical pass needs is in the node's own structure: `node.expr` is the blob `Field` (its `.type` is the source
# `FieldType` → table_type → property registry) and `node.keys` is the key path (keys[0] is the top-level property name,
# deeper keys index into the extracted value). We read from there, never from `node.type`.


def _blob_field_type_of(node: ast.JSONFieldAccess) -> ast.FieldType | None:
    """The source blob column's `FieldType` (`node.expr.type`), the input to `resolve_materialized_property_source`."""
    expr_type = node.expr.type
    return expr_type if isinstance(expr_type, ast.FieldType) else None


def _is_json_blob_access(node: ast.JSONFieldAccess, context: HogQLContext) -> bool:
    """Whether this `JSONFieldAccess` reads a JSON blob column (`properties` / `person_properties`).

    Lowering only produces `JSONFieldAccess` over a `StringJSONDatabaseField`, but guard defensively so the physical pass
    never mistakes some other lowered access for a materializable property.
    """
    field_type = _blob_field_type_of(node)
    if field_type is None:
        return False
    return isinstance(field_type.resolve_database_field(context), StringJSONDatabaseField)


# --- value substitution: rebuild the printer's materialized-column read as AST ----------------------------------------


def _sentinel(value: str) -> ast.Constant:
    """A fixed materialization sentinel constant ('' / 'null' / the trim regex), rendered inline like the printer.

    These are fixed, known-safe literals; `inline=True` makes the ClickHouse printer emit them inline (escaped) exactly
    as `BasePrinter.visit_property_type` hand-builds them, so the lowered SQL is byte-identical, not merely result-
    equivalent (§8.7). They do not affect skip-index eligibility (which depends on the *column* being bare).
    """
    return ast.Constant(value=value, inline=True)


def _blob_field(field_type: ast.FieldType) -> ast.Field:
    """A Field over the raw JSON blob column (`properties` / `person_properties`), reusing its resolved type.

    Printing this Field runs the ClickHouse printer's `visit_field_type`, which `JSONDropKeys`-wraps it for restricted
    properties — so a restricted read scrubs to '' exactly as on master.
    """
    return ast.Field(chain=[field_type.name], type=field_type)


def _json_extract_trim_quotes_expr(field_expr: ast.Expr, keys: list[str | int]) -> ast.Expr:
    """AST form of clickhouse.kafka_engine.json_extract_trim_quotes(field, *keys).

    Integer keys (array indices) are emitted as integer constants so JSONExtractRaw indexes the array; string keys are
    object lookups. Mirrors the printer passing the raw chain values through untyped.
    """
    extract = ast.Call(name="JSONExtractRaw", args=[field_expr, *[ast.Constant(value=key) for key in keys]])
    scrubbed = ast.Call(
        name="nullIf",
        args=[ast.Call(name="nullIf", args=[extract, _sentinel("")]), _sentinel("null")],
    )
    return ast.Call(name="replaceRegexpAll", args=[scrubbed, _sentinel('^"|"$'), _sentinel("")])


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


def _synthetic_column_field(
    field_type: ast.FieldType, column_name: str, *, is_nullable: bool, unqualified: bool = False
) -> ast.Field | None:
    """A typed Field for a physical ClickHouse column that isn't a HogQL schema field.

    Mat/dmat/property-group columns live on the table physically but aren't in the HogQL schema, so a plain Field won't
    resolve. Synthesize a DatabaseField on a copy of the table and point a fresh FieldType at it, preserving any alias
    wrapper so the printed table prefix (`events.` / `e.`) is unchanged. On the within_non_hogql_query path `unqualified`
    is set so the printer drops the prefix — the lightweight-DELETE mutation analyzer rejects qualified column names.
    """
    table_type = _augment_table_type(field_type.table_type, column_name, is_nullable=is_nullable)
    if table_type is None:
        return None
    return ast.Field(
        chain=[column_name],
        type=ast.FieldType(name=column_name, table_type=table_type, unqualified=unqualified or None),
    )


def _materialized_head_expr(
    source: MaterializedPropertySource,
    field_type: ast.FieldType,
    first_key: str,
    *,
    is_single: bool,
    materialization_mode: MaterializationMode | None,
    unqualified: bool = False,
) -> ast.Expr | None:
    """The chain[0] value read for a materialized source — mirrors the branches in BasePrinter.visit_property_type."""
    if source.kind == "property_group":
        # `has(g, k) ? g[k] : null` — guard the map read so a missing key returns NULL, not the '' map default.
        has_field = _synthetic_column_field(field_type, source.column, is_nullable=True, unqualified=unqualified)
        get_field = _synthetic_column_field(field_type, source.column, is_nullable=True, unqualified=unqualified)
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
        field_type, source.column, is_nullable=source.is_nullable, unqualified=unqualified
    )
    if column_field is None:
        return None

    # Nullable columns (dmat, nullable mat) and the index-friendly $ai single-key columns are read bare.
    if source.is_nullable or (is_single and first_key in AI_PROPERTIES_WITHOUT_NULLIF):
        return column_field

    # Non-nullable materialized column: scrub the '' / 'null' string sentinels back to NULL.
    scrubbed_empty = ast.Call(name="nullIf", args=[column_field, _sentinel("")])
    if materialization_mode == MaterializationMode.LEGACY_NULL_AS_STRING:
        return scrubbed_empty
    return ast.Call(name="nullIf", args=[scrubbed_empty, _sentinel("null")])


def _substitute_value_read(node: ast.JSONFieldAccess, context: HogQLContext) -> ast.Expr | None:
    """The materialized-column value read for a `JSONFieldAccess`, or None to leave it as the JSON-blob extract.

    Mirrors `BasePrinter.visit_property_type` column selection (NOT the scalar cast — that already wraps this node, since
    the swapper ran before lowering). Returns None when there is no physical backing or the property is restricted.
    """
    field_type = _blob_field_type_of(node)
    if field_type is None or not node.keys:
        return None
    if not _is_json_blob_access(node, context):
        return None

    first_key = str(node.keys[0])
    deeper_keys: list[str | int] = list(node.keys[1:])

    # §8.5 security boundary: a restricted property must not be read from its materialized column. Decline so the
    # JSON-blob extract is rendered; the printer's visit_field_type JSONDropKeys-wraps it and the value collapses to ''.
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
        unqualified=context.within_non_hogql_query,
    )
    if head is None:
        return None
    # Deeper keys read the materialized value as a JSON string, same as the printer's chain[1:] handling.
    return head if not deeper_keys else _json_extract_trim_quotes_expr(head, deeper_keys)


# --- optimized comparison forms: reproduce the printer's skip-index-friendly rewrites as AST --------------------------
#
# These mirror ClickHousePrinter._get_optimized_* (posthog/hogql/printer/clickhouse.py). The printer detects a property
# operand and rewrites the comparison so the bare materialized column / property-group map access stays eligible for
# ClickHouse skip indexes. This pass consumes the operand and emits the optimized form as result-equivalent AST (only
# registered HogQL functions, parameterized constants). Functionality (results + index eligibility), not byte-exact SQL,
# is the bar (§8.7).


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


def _is_null_constant(expr: ast.Expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def _resolve_field_type(expr: ast.Expr) -> ast.Type | None:
    """An operand's resolved type, unwrapping field-alias wrappers. Mirrors printer.resolve_field_type."""
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    return expr_type


def _and_all(clauses: list[ast.Expr]) -> ast.Expr:
    """`and(...)` over the clauses (single clause returned bare). The printer renders chained `AND`; result-equivalent."""
    if len(clauses) == 1:
        return clauses[0]
    return _call("and", clauses)


def _string_pattern_constant(expr: ast.Expr) -> ast.Constant | None:
    return expr if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


@dataclass(frozen=True)
class _OptimizableProperty:
    """A single-key materializable property operand of a comparison, paired with its resolved physical source.

    `field_type` is the source blob column's type (from the operand's `JSONFieldAccess.expr`, or the blob `Field` directly
    on the `JSONHas(blob, key)` path); `key` is the top-level property name; `source` is its resolved physical column. The
    group/column builders read only these three — the node no longer carries a `PropertyType` to recover (§4.4).
    """

    field_type: ast.FieldType
    key: str
    source: MaterializedPropertySource
    # Set on the within_non_hogql_query (lightweight-DELETE) path so the synthetic column fields below print unqualified.
    unqualified: bool = False


def _group_map_field(prop: _OptimizableProperty) -> ast.Field:
    """The property-group `Map(String, String)` column, read non-nullable so map access / has() print bare.

    The map column is non-nullable; a missing key yields the type default (''), not SQL NULL. Marking the synthetic field
    non-nullable keeps the printer from ifNull-wrapping `equals(g[k], v)` (which would defeat the values bloom-filter
    index).
    """
    field = _synthetic_column_field(
        prop.field_type, prop.source.column, is_nullable=False, unqualified=prop.unqualified
    )
    assert field is not None  # the source was resolved from this same field_type
    return field


def _group_has_expr(prop: _OptimizableProperty) -> ast.Call:
    """`has(group_map_column, key)` — mirrors PrintableMaterializedPropertyGroupItem.has_expr."""
    return _call("has", [_group_map_field(prop), _const(prop.key)])


def _group_value_expr(prop: _OptimizableProperty) -> ast.ArrayAccess:
    """`group_map_column[key]`, typed non-nullable String — mirrors PrintableMaterializedPropertyGroupItem.value_expr.

    Map access over `Map(String, String)` returns the non-nullable value type, a missing key yielding the '' default. The
    explicit type stops the printer from ifNull-wrapping `equals(g[k], v)`, which would defeat the values bloom filter.
    """
    return ast.ArrayAccess(array=_group_map_field(prop), property=_const(prop.key), type=ast.StringType(nullable=False))


def _bare_mat_column(prop: _OptimizableProperty) -> ast.Field:
    """The materialized column read bare (no nullIf scrubbing), typed non-nullable.

    Typed non-nullable so the printer's `visit_compare_operation` sees `not_nullable` and does NOT wrap the comparison in
    `ifNull(..., 0)` — the very wrapping that hides the column from skip indexes. The real ClickHouse column may be
    Nullable; nullability is handled explicitly by the optimizer (an `isNotNull(col)` guard or an `ifNull(...)` around the
    whole result), exactly as the printer's string-built optimized forms do.
    """
    field = _synthetic_column_field(
        prop.field_type, prop.source.column, is_nullable=False, unqualified=prop.unqualified
    )
    assert field is not None
    return field


def _is_not_null(prop: _OptimizableProperty) -> ast.Call:
    """`isNotNull(col)` over a nullable view of the column — result-equivalent to the printer's `col IS NOT NULL`."""
    field = _synthetic_column_field(prop.field_type, prop.source.column, is_nullable=True, unqualified=prop.unqualified)
    assert field is not None
    return _call("isNotNull", [field])


class ClickHousePhysicalPasses(CloningVisitor):
    """Rewrites lowered `JSONFieldAccess` reads (and comparisons over them) to physical ClickHouse forms.

    Runs on a resolved, swapped, logically-lowered ClickHouse AST. After this pass the materializable accesses are
    ordinary typed column expressions; an un-backed (or restricted) access remains a `JSONFieldAccess` that prints as the
    JSON-blob extract.
    """

    def __init__(self, context: HogQLContext) -> None:
        # §8.6: the AST is printed directly after this pass, so keep resolved types rather than clearing them.
        super().__init__(clear_types=False)
        self.context = context
        # Per-select-scope map of column alias → its lowered property read, so a comparison referencing the alias
        # (`SELECT properties.x AS a ... WHERE a = 'v'`) can still resolve to the property and be optimized — the printer
        # did this implicitly via `resolve_field_type`, which unwrapped the alias back to the `PropertyType`.
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
        """A lowered `properties.$x` comparison operand, unwrapping an `Alias` or resolving a select-alias ref, or None.

        §4.4: after logical lowering a `properties.$x` operand is a `JSONFieldAccess` (often `Alias`-wrapped), detected
        directly by class. A bare `Field` that *references* a select-column alias over such a read (`... WHERE a = 'v'`)
        is resolved back to it via the scope map, mirroring the printer's old `resolve_field_type` alias unwrapping.
        """
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        if isinstance(expr, ast.JSONFieldAccess):
            return expr
        return self._resolve_alias_to_property(expr)

    def _single_key_property(self, expr: ast.Expr) -> tuple[ast.FieldType, str] | None:
        """The (blob `FieldType`, top-level key) of a single-key lowered property operand, or None.

        Mirrors the printer's `len(chain) == 1` guard: only a single-key access (no deeper `.a.b`) is an individually-
        materializable / property-group property. Multi-key accesses read the materialized value then JSON-extract
        deeper, so they are not eligible for the bare-column comparison optimizers.
        """
        node = self._lowered_property_operand(expr)
        if node is not None and len(node.keys) == 1:
            field_type = _blob_field_type_of(node)
            if field_type is not None:
                return field_type, str(node.keys[0])

        # Fallback: an operand whose resolved type is still a single-key `PropertyType`. Lowering leaves the
        # `PropertyType` on an alias whose expr is NOT a bare `JSONFieldAccess` — e.g. a boolean/numeric property the
        # swapper wrapped in `toBool(transform(toString(...)))` and then aliased. The JSON read is buried inside the
        # cast, so detect the property from the resolved type instead, mirroring the printer's old
        # `resolve_field_type`-based detection (the optimizer then discards the cast wrapper, as the printer did).
        prop_type = _resolve_field_type(expr)
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
        # `isNull`/`isNotNull`/`JSONHas` on a property-group property can read the keys-only `has(g, k)` instead of the
        # values subcolumn — staying eligible for the keys bloom-filter index. Mirrors
        # ClickHousePrinter._get_optimized_property_group_call.
        optimized = self._optimize_property_group_call(node)
        if optimized is not None:
            return optimized

        # Comparison functions in call form (`equals(properties.x, v)`, `ilike(toString(properties.x), p)`,
        # `in(properties.x, (...))`) are comparisons in disguise — the printer routes them through
        # visit_compare_operation. Do the same so the same skip-index optimizers fire (otherwise we'd recurse into the
        # args and substitute the value, defeating the optimization). Only the plain 2-arg form, no params.
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
        # Reproduce the printer's skip-index comparison optimizers as AST, in the printer's dispatch order
        # (clickhouse.visit_compare_operation). Each consumes the property operand and returns the optimized form, so we
        # must NOT also substitute the value. Session-id is intentionally left to the printer (doc §4.5).
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

        # KNOWN: is-set over a materialized column over-matches — see PRINTER_REARCHITECTURE.md §12.7. No comparison
        # optimizer fires for `property = NULL` / `!= NULL`, so we recurse via super(); the surviving JSONFieldAccess
        # operand goes through value substitution and reads the scrubbed materialized column. On master, is-set over a
        # materialized column reads `isNull(nullIf(nullIf(mat_X, ''), 'null'))`, collapsing empty-string and the literal
        # "null" string to "not set". Substituting the value here reproduces that exact over-match (preserve master,
        # decision A); the truthful blob key-existence fix is deferred to a separate signed-off change.
        return super().visit_compare_operation(node)

    # --- property operand detection (mirrors ClickHousePrinter._get_materialized_string_property_source) ---

    def _materialized_string_property(self, expr: ast.Expr) -> _OptimizableProperty | None:
        """A single-key string property backed by an individually materialized column, or None.

        Mirrors ClickHousePrinter._get_materialized_string_property_source: unwraps a `toString(properties.x)` safety
        wrapper, requires a single-key chain, skips properties with a non-string resolved type, and requires the property
        to back a `materialized_column` (not a property group). After lowering the property operand is a `JSONFieldAccess`
        (`Alias`-wrapped), detected directly by `_single_key_property`; the `toString(...)` form unwraps to the same node.
        """
        single = self._single_key_property(expr)
        if single is None and isinstance(expr, ast.Call) and expr.name == "toString" and len(expr.args) == 1:
            # Only match a direct lowered property read, not toString(toFloat(...)) — same intent as the printer's
            # `isinstance(inner, ast.Field)` guard, adapted to the post-lowering JSONFieldAccess leaf.
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
            unqualified=self.context.within_non_hogql_query,
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
            unqualified=self.context.within_non_hogql_query,
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
            # JSONHas's key is the literal; resolve the group source for that key off the blob field. The blob field is
            # `node.args[0]` — after lowering it is a `JSONFieldAccess`'s source Field (the raw blob), so resolve its
            # FieldType directly.
            field_expr = node.args[0]
            field_type = _resolve_field_type(field_expr)
            if not isinstance(field_type, ast.FieldType):
                return None
            key = str(node.args[1].value)
            # JSONHas answers key-existence from the property group even when a mat column exists, so resolve the group
            # directly (the mat-column-first resolver would shadow it).
            source = resolve_property_group_source(field_type, key, self.context)
            if source is None or source.kind != "property_group":
                return None
            return _group_has_expr(
                _OptimizableProperty(
                    field_type=field_type,
                    key=key,
                    source=source,
                    unqualified=self.context.within_non_hogql_query,
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
                # Booleans are stored as the fixed strings 'true'/'false' in the group map; inline them (like the
                # printer's hand-built literal) so the comparison stays byte-identical and values-index-eligible.
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
                    return _call("and", [_call("like", [indexed, _lower(_const(pattern.value))]), _is_not_null(prop)])
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


def clickhouse_physical_passes(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Rewrite every materializable lowered `JSONFieldAccess` (and comparison over it) to its physical ClickHouse form.

    ClickHouse-only. Expects a resolved, swapped, logically-lowered AST. Dormant: not wired into the print pipeline this
    round (doc §12.3) — call it explicitly after `lower_property_access` to exercise the physical optimizations.
    """
    return cast(_T_AST, ClickHousePhysicalPasses(context).visit(node))
