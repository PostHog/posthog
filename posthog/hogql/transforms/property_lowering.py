from dataclasses import dataclass
from typing import Literal, cast

from posthog.schema import MaterializationMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn

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

    table_name = table_type.table.to_printed_hogql()
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
        if property_info and property_info.get("dmat"):
            return MaterializedPropertySource(kind="dmat", column=property_info["dmat"], is_nullable=True)

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

    # Property-level access control rewrites the read into a JSONDropKeys-wrapped blob extract in the printer.
    # Leave those to the printer for now rather than duplicate the restriction logic here.
    if context.restricted_properties:
        return None

    chain = property_type.chain
    if not chain:
        return None

    base_field_type = property_type.field_type
    # Only plain physical tables (optionally aliased) can host the synthetic mat/dmat/group columns.
    if _underlying_table_type(base_field_type.table_type) is None:
        return None

    first_key = str(chain[0])
    deeper_keys = [str(link) for link in chain[1:]]

    source = resolve_materialized_property_source(base_field_type, first_key, context)

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
    if source.kind == "property_group":
        # `has(g, k) ? g[k] : null` — guard the map read so a missing key returns NULL, not the '' map default.
        has_field = _synthetic_column_field(base_field_type, source.column, is_nullable=True)
        get_field = _synthetic_column_field(base_field_type, source.column, is_nullable=True)
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

    column_field = _synthetic_column_field(base_field_type, source.column, is_nullable=source.is_nullable)
    if column_field is None:
        return None

    # Nullable columns (dmat, nullable mat) and the index-friendly $ai single-key columns are read bare.
    if source.is_nullable or (is_single and first_key in AI_PROPERTIES_WITHOUT_NULLIF):
        return column_field

    # Non-nullable materialized column: scrub the '' / 'null' string sentinels back to NULL.
    scrubbed_empty = ast.Call(name="nullIf", args=[column_field, ast.Constant(value="")])
    if context.modifiers.materializationMode == MaterializationMode.LEGACY_NULL_AS_STRING:
        return scrubbed_empty
    return ast.Call(name="nullIf", args=[scrubbed_empty, ast.Constant(value="null")])


def _json_extract_trim_quotes_expr(field_expr: ast.Expr, keys: list[str]) -> ast.Expr:
    """AST form of clickhouse.kafka_engine.json_extract_trim_quotes(field, *keys)."""
    extract = ast.Call(
        name="JSONExtractRaw",
        args=[field_expr, *[ast.Constant(value=key) for key in keys]],
    )
    scrubbed = ast.Call(
        name="nullIf",
        args=[
            ast.Call(name="nullIf", args=[extract, ast.Constant(value="")]),
            ast.Constant(value="null"),
        ],
    )
    return ast.Call(name="replaceRegexpAll", args=[scrubbed, ast.Constant(value='^"|"$'), ast.Constant(value="")])


def _blob_field(base_field_type: ast.FieldType) -> ast.Field:
    """A Field over the raw JSON blob column (`properties` / `person_properties`), reusing its resolved type."""
    return ast.Field(chain=[base_field_type.name], type=base_field_type)


def _synthetic_column_field(base_field_type: ast.FieldType, column_name: str, *, is_nullable: bool) -> ast.Field | None:
    """A typed Field for a physical ClickHouse column that isn't a HogQL schema field.

    Mat/dmat/property-group columns live on the table physically but aren't in the HogQL schema, so a plain
    Field won't resolve. Synthesize a DatabaseField on a copy of the table and point a fresh FieldType at it,
    preserving any alias wrapper so the printed table prefix (`events.` / `e.`) is unchanged. Mirrors the
    pushdown transform's `_inner_table_type_with_materialized_columns`.
    """
    table_type = _augment_table_type(base_field_type.table_type, column_name, is_nullable=is_nullable)
    if table_type is None:
        return None
    return ast.Field(chain=[column_name], type=ast.FieldType(name=column_name, table_type=table_type))


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


def lower_properties(node: ast.Expr, context: HogQLContext) -> ast.Expr:
    """Lower every materializable `properties.$x` access in a resolved ClickHouse AST to concrete column AST."""
    return LowerProperties(context).visit(node)
