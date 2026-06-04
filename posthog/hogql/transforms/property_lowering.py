from dataclasses import dataclass
from typing import Literal, cast

from posthog.schema import PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField

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
