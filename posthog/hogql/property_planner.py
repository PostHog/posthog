import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.errors import (
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
    ResolutionError,
)
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.type_system import (
    ComparisonCompatibility,
    comparison_compatibility,
    constant_type_from_runtime_type,
    parse_sql_runtime_type,
    runtime_type_from_constant_type,
)

from posthog.clickhouse.materialized_columns import (
    MATERIALIZATION_VALID_TABLES,
    MaterializedColumn,
    TablesWithMaterializedColumns,
    get_materialized_column_for_property,
)
from posthog.clickhouse.property_groups import property_groups
from posthog.models.event.sql import (
    EVENTS_JSON_INDEXED_PROPERTY_NAMES,
    EVENTS_PROPERTIES_JSON_SUBCOLUMNS,
    PERSON_PROPERTIES_JSON_SUBCOLUMNS,
)
from posthog.models.property import PropertyName, TableColumn
from posthog.schema_enums import PropertyGroupsMode

from products.event_definitions.backend.models.property_definition import PropertyType


class PropertyScope(StrEnum):
    EVENT = "event"
    PERSON = "person"
    GROUP = "group"
    UNKNOWN = "unknown"


class PropertySourceKind(StrEnum):
    JSON = "json"
    MATERIALIZED_COLUMN = "materialized_column"
    DYNAMIC_MATERIALIZED_COLUMN = "dynamic_materialized_column"
    PROPERTY_GROUP = "property_group"


class PropertyMinmaxBlocker(StrEnum):
    NO_MINMAX_INDEX = "no_minmax_index"
    SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE = "source_type_differs_from_property_type"
    VALUE_TYPE_NOT_SOURCE_COMPATIBLE = "value_type_not_source_compatible"


class PropertyLiteralConversion(StrEnum):
    NONE = "none"
    DATETIME = "datetime"


@dataclass(frozen=True, slots=True)
class PropertySourcePlan:
    kind: PropertySourceKind
    table_name: str | None
    field_name: str | None
    column_name: str | None
    physical_type: ast.ConstantType
    is_nullable: bool
    has_minmax_index: bool = False
    has_bloom_filter_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_lower_index: bool = False
    restricted: bool = False


@dataclass(frozen=True, slots=True)
class PropertyAccessPlan:
    property_name: str
    scope: PropertyScope
    semantic_type: ast.ConstantType
    source: PropertySourcePlan
    property_type: ast.PropertyType


@dataclass(frozen=True, slots=True)
class PropertyComparisonPlan:
    access: PropertyAccessPlan
    property_side: Literal["left", "right"]
    operator: ast.CompareOperationOp
    value_type: ast.ConstantType
    semantic_compatibility: ComparisonCompatibility
    physical_compatibility: ComparisonCompatibility
    literal_conversion: PropertyLiteralConversion
    source_matches_semantics: bool
    minmax_blocker: PropertyMinmaxBlocker | None

    @property
    def can_use_minmax_index(self) -> bool:
        return self.minmax_blocker is None

    @property
    def can_compare_physical_source_directly(self) -> bool:
        return self.source_matches_semantics and (
            self.physical_compatibility in _OPTIMIZER_COMPATIBLE_COMPARISONS
            or self.literal_conversion != PropertyLiteralConversion.NONE
        )


def plan_property_comparison(node: ast.CompareOperation, context: HogQLContext) -> PropertyComparisonPlan | None:
    left_plan = plan_property_access(node.left, context)
    if left_plan is not None:
        return _build_property_comparison_plan(
            access=left_plan,
            property_side="left",
            operator=node.op,
            value_expr=node.right,
            value_type=_constant_type_from_expr(node.right, context),
        )

    right_plan = plan_property_access(node.right, context)
    if right_plan is not None:
        return _build_property_comparison_plan(
            access=right_plan,
            property_side="right",
            operator=node.op,
            value_expr=node.left,
            value_type=_constant_type_from_expr(node.left, context),
        )

    return None


def plan_property_access(expr: ast.Expr, context: HogQLContext) -> PropertyAccessPlan | None:
    extracted = _extract_property_access(expr, context)
    if extracted is None:
        return None

    property_type, semantic_type = extracted
    if len(property_type.chain) != 1:
        return None

    property_name = str(property_type.chain[0])
    source = _plan_property_source(property_type=property_type, property_name=property_name, context=context)
    return PropertyAccessPlan(
        property_name=property_name,
        scope=_property_scope(property_type, context),
        semantic_type=semantic_type,
        source=source,
        property_type=property_type,
    )


def is_property_type_restricted(property_type: ast.PropertyType, context: HogQLContext) -> bool:
    if not context.restricted_properties or len(property_type.chain) == 0:
        return False
    keys_to_drop = get_restricted_keys_for_table_type(property_type.field_type.table_type, context)
    if not keys_to_drop:
        return False
    return str(property_type.chain[0]) in keys_to_drop


def get_restricted_keys_for_table_type(table_type: ast.Type, context: HogQLContext) -> set[str]:
    # Delegates to the single source of truth for property-level access control; see its docstring.
    return restricted_property_keys_for_table_type(table_type, context)


def _build_property_comparison_plan(
    access: PropertyAccessPlan,
    property_side: Literal["left", "right"],
    operator: ast.CompareOperationOp,
    value_expr: ast.Expr,
    value_type: ast.ConstantType,
) -> PropertyComparisonPlan:
    semantic_compatibility = comparison_compatibility(access.semantic_type, value_type)
    physical_compatibility = comparison_compatibility(access.source.physical_type, value_type)
    literal_conversion = _literal_conversion_for_value(access.source.physical_type, value_type, value_expr)
    source_matches_semantics = (
        comparison_compatibility(access.semantic_type, access.source.physical_type) in _OPTIMIZER_COMPATIBLE_COMPARISONS
    )

    minmax_blocker = _minmax_blocker(
        access=access,
        source_matches_semantics=source_matches_semantics,
        physical_compatibility=physical_compatibility,
        literal_conversion=literal_conversion,
    )
    return PropertyComparisonPlan(
        access=access,
        property_side=property_side,
        operator=operator,
        value_type=value_type,
        semantic_compatibility=semantic_compatibility,
        physical_compatibility=physical_compatibility,
        literal_conversion=literal_conversion,
        source_matches_semantics=source_matches_semantics,
        minmax_blocker=minmax_blocker,
    )


_OPTIMIZER_COMPATIBLE_COMPARISONS = {
    ComparisonCompatibility.DEFINITELY_COMPATIBLE,
    ComparisonCompatibility.CHEAP_CAST,
}


def _minmax_blocker(
    access: PropertyAccessPlan,
    source_matches_semantics: bool,
    physical_compatibility: ComparisonCompatibility,
    literal_conversion: PropertyLiteralConversion,
) -> PropertyMinmaxBlocker | None:
    if not access.source.has_minmax_index:
        return PropertyMinmaxBlocker.NO_MINMAX_INDEX
    if not source_matches_semantics:
        return PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE
    if (
        physical_compatibility not in _OPTIMIZER_COMPATIBLE_COMPARISONS
        and literal_conversion == PropertyLiteralConversion.NONE
    ):
        return PropertyMinmaxBlocker.VALUE_TYPE_NOT_SOURCE_COMPATIBLE
    return None


def _literal_conversion_for_value(
    source_type: ast.ConstantType,
    value_type: ast.ConstantType,
    value_expr: ast.Expr,
) -> PropertyLiteralConversion:
    value_expr = _unwrap_alias(value_expr)
    if not isinstance(value_expr, ast.Constant) or value_expr.value is None:
        return PropertyLiteralConversion.NONE

    source_family = runtime_type_from_constant_type(source_type).family
    value_family = runtime_type_from_constant_type(value_type).family
    if source_family == "datetime" and value_family == "string":
        return PropertyLiteralConversion.DATETIME

    return PropertyLiteralConversion.NONE


def _extract_property_access(expr: ast.Expr, context: HogQLContext) -> tuple[ast.PropertyType, ast.ConstantType] | None:
    expr = _unwrap_alias(expr)
    expr_type = _resolve_expr_type(expr)
    if isinstance(expr_type, ast.PropertyType):
        return expr_type, _semantic_type_for_property_type(expr_type, context)

    if not isinstance(expr, ast.Call):
        return None

    normalized_name = expr.name.lower()
    if len(expr.args) == 1:
        semantic_type_class = _PROPERTY_CONVERSION_SEMANTIC_TYPES.get(normalized_name)
        if semantic_type_class is not None:
            inner = _extract_property_access(expr.args[0], context)
            if inner is not None:
                return inner[0], semantic_type_class(nullable=True)
        if normalized_name == "tobool":
            inner = _extract_property_access_from_boolean_conversion(expr.args[0], context)
            if inner is not None:
                return inner[0], ast.BooleanType(nullable=True)

    return None


_PROPERTY_CONVERSION_SEMANTIC_TYPES: dict[str, type[ast.FloatType] | type[ast.DateTimeType] | type[ast.StringType]] = {
    "tofloat": ast.FloatType,
    "todatetime": ast.DateTimeType,
    "tostring": ast.StringType,
}


def _extract_property_access_from_boolean_conversion(
    expr: ast.Expr, context: HogQLContext
) -> tuple[ast.PropertyType, ast.ConstantType] | None:
    expr = _unwrap_alias(expr)
    if not isinstance(expr, ast.Call) or len(expr.args) == 0:
        return _extract_property_access(expr, context)

    normalized_name = expr.name.lower()
    if normalized_name == "transform":
        return _extract_property_access_from_boolean_conversion(expr.args[0], context)
    if normalized_name == "tostring" and len(expr.args) == 1:
        return _extract_property_access(expr.args[0], context)
    return None


def _plan_property_source(
    property_type: ast.PropertyType, property_name: str, context: HogQLContext
) -> PropertySourcePlan:
    table_info = _materialized_table_info(property_type.field_type, context)
    if table_info is None:
        return _json_source_plan(context=context)

    table_name, field_name = table_info
    restricted = is_property_type_restricted(property_type, context)
    if restricted or context.modifiers.materializationMode == "disabled":
        return _json_source_plan(
            table_name=table_name,
            field_name=field_name,
            property_name=property_name,
            restricted=restricted,
            context=context,
        )

    if (
        context.uses_new_events_schema()
        and table_name == "events"
        and field_name
        in (
            "properties",
            "person_properties",
        )
    ):
        return _json_source_plan(
            table_name=table_name, field_name=field_name, property_name=property_name, context=context
        )

    materialized_column = get_materialized_column_for_property(
        cast(TablesWithMaterializedColumns, table_name),
        cast(TableColumn, field_name),
        cast(PropertyName, property_name),
    )
    if materialized_column is not None:
        return PropertySourcePlan(
            kind=PropertySourceKind.MATERIALIZED_COLUMN,
            table_name=table_name,
            field_name=field_name,
            column_name=materialized_column.name,
            physical_type=_materialized_column_physical_type(materialized_column),
            is_nullable=materialized_column.is_nullable,
            has_minmax_index=materialized_column.has_minmax_index,
            has_bloom_filter_index=materialized_column.has_bloom_filter_index,
            has_ngram_lower_index=materialized_column.has_ngram_lower_index,
            has_bloom_filter_lower_index=materialized_column.has_bloom_filter_lower_index,
        )

    if dmat_column := get_dmat_column(context, table_name, field_name, property_name):
        return PropertySourcePlan(
            kind=PropertySourceKind.DYNAMIC_MATERIALIZED_COLUMN,
            table_name=table_name,
            field_name=field_name,
            column_name=dmat_column,
            physical_type=ast.StringType(nullable=True),
            is_nullable=True,
        )

    if context.modifiers.propertyGroupsMode in (PropertyGroupsMode.ENABLED, PropertyGroupsMode.OPTIMIZED):
        for property_group_column in property_groups.get_property_group_columns(table_name, field_name, property_name):
            return PropertySourcePlan(
                kind=PropertySourceKind.PROPERTY_GROUP,
                table_name=table_name,
                field_name=field_name,
                column_name=property_group_column,
                physical_type=ast.StringType(nullable=True),
                is_nullable=True,
                has_bloom_filter_index=True,
            )

    return _json_source_plan(table_name=table_name, field_name=field_name, property_name=property_name, context=context)


def _json_source_plan(
    table_name: str | None = None,
    field_name: str | None = None,
    property_name: str | None = None,
    restricted: bool = False,
    context: HogQLContext | None = None,
) -> PropertySourcePlan:
    has_minmax_index = _json_source_has_index(table_name, field_name, property_name, "minmax", context)
    has_bloom_filter_index = _json_source_has_index(table_name, field_name, property_name, "bloom_filter", context)
    physical_type = _json_source_physical_type(table_name, field_name, property_name, context)

    return PropertySourcePlan(
        kind=PropertySourceKind.JSON,
        table_name=table_name,
        field_name=field_name,
        column_name=field_name,
        physical_type=physical_type,
        is_nullable=physical_type.nullable,
        has_minmax_index=has_minmax_index,
        has_bloom_filter_index=has_bloom_filter_index,
        restricted=restricted,
    )


def _json_source_physical_type(
    table_name: str | None,
    field_name: str | None,
    property_name: str | None,
    context: HogQLContext | None,
) -> ast.ConstantType:
    if context is None or not context.uses_new_events_schema():
        return ast.StringType(nullable=True)
    if table_name != "events" or property_name is None:
        return ast.StringType(nullable=True)

    subcolumns = {
        "properties": EVENTS_PROPERTIES_JSON_SUBCOLUMNS,
        "person_properties": PERSON_PROPERTIES_JSON_SUBCOLUMNS,
    }.get(field_name)
    if subcolumns is None or property_name not in subcolumns:
        return ast.StringType(nullable=True)
    return constant_type_from_runtime_type(parse_sql_runtime_type(subcolumns[property_name]))


def _json_source_has_index(
    table_name: str | None,
    field_name: str | None,
    property_name: str | None,
    index_type: str,
    context: HogQLContext | None,
) -> bool:
    if context is None or not context.uses_new_events_schema():
        return False
    if table_name != "events" or field_name not in ("properties", "person_properties") or property_name is None:
        return False
    return property_name in EVENTS_JSON_INDEXED_PROPERTY_NAMES(field_name, index_type)


def _unwrap_table_type(table_type: ast.Type) -> ast.Type:
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        table_type = table_type.table_type
    return table_type


def _materialized_table_info(field_type: ast.FieldType, context: HogQLContext) -> tuple[str, str] | None:
    table = _unwrap_table_type(field_type.table_type)

    if not isinstance(table, ast.TableType):
        return None

    resolved_table = table.resolve_database_table(context)
    table_name = "person" if isinstance(resolved_table, RawPersonsTable) else resolved_table.to_printed_hogql()
    if table_name not in MATERIALIZATION_VALID_TABLES:
        return None

    field = field_type.resolve_database_field(context)
    if not isinstance(field, DatabaseField):
        return None

    return table_name, field.name


def _materialized_column_physical_type(materialized_column: MaterializedColumn) -> ast.ConstantType:
    runtime_type = parse_sql_runtime_type(materialized_column.type)
    if runtime_type.family != "unknown":
        return constant_type_from_runtime_type(
            runtime_type.with_nullable(runtime_type.nullable or materialized_column.is_nullable)
        )

    return ast.StringType(nullable=materialized_column.is_nullable)


def get_dmat_column(context: HogQLContext, table_name: str, field_name: str, property_name: str) -> str | None:
    """Dynamically materialized (dmat) column name for a property, if a slot is assigned."""
    if context.property_swapper is None:
        return None
    if table_name != "events" or field_name != "properties":
        return None
    prop_info = context.property_swapper.event_properties.get(property_name)
    if prop_info is None:
        return None
    return prop_info.get("dmat")


def metadata_constant_type(property_type: ast.PropertyType, context: HogQLContext) -> ast.ConstantType | None:
    """Semantic constant type from property-definition metadata, or None when no metadata applies."""
    property_info = _property_info_for_property_type(property_type, context)
    if property_info is None:
        return None
    return _semantic_type_from_property_definition_type(property_info.get("type"))


def _semantic_type_for_property_type(property_type: ast.PropertyType, context: HogQLContext) -> ast.ConstantType:
    return metadata_constant_type(property_type, context) or ast.StringType(nullable=True)


def _semantic_type_from_property_definition_type(property_type: str | None) -> ast.ConstantType | None:
    if property_type in (PropertyType.Numeric, PropertyType.Duration):
        return ast.FloatType(nullable=True)
    if property_type == PropertyType.Datetime:
        return ast.DateTimeType(nullable=True)
    if property_type == PropertyType.Boolean:
        return ast.BooleanType(nullable=True)
    if property_type == PropertyType.String:
        return ast.StringType(nullable=True)
    return None


def _property_info_for_property_type(
    property_type: ast.PropertyType, context: HogQLContext
) -> dict[str, str | None] | None:
    if context.property_swapper is None or len(property_type.chain) != 1:
        return None

    property_name = str(property_type.chain[0])
    scope = _property_scope(property_type, context)
    if scope == PropertyScope.EVENT:
        return context.property_swapper.event_properties.get(property_name)
    if scope == PropertyScope.PERSON:
        return context.property_swapper.person_properties.get(property_name)
    if scope == PropertyScope.GROUP:
        group_property_name = _group_property_name(property_type, context, property_name)
        if group_property_name is None:
            return None
        return context.property_swapper.group_properties.get(group_property_name)
    return None


def _property_scope(property_type: ast.PropertyType, context: HogQLContext) -> PropertyScope:
    field_type = property_type.field_type
    if field_type.name == "person_properties":
        return PropertyScope.PERSON

    table_type = field_type.table_type
    if isinstance(table_type, ast.VirtualTableType) and table_type.field == "poe" and field_type.name == "properties":
        return PropertyScope.PERSON

    unwrapped_table_type = _unwrap_table_type(table_type)
    if not isinstance(unwrapped_table_type, ast.BaseTableType):
        return PropertyScope.UNKNOWN

    try:
        resolved_table = unwrapped_table_type.resolve_database_table(context)
    except (HogQLNotImplementedError, QueryError, ResolutionError):
        return PropertyScope.UNKNOWN

    if isinstance(resolved_table, EventsTable):
        return PropertyScope.EVENT
    if isinstance(resolved_table, (EventsPersonSubTable, PersonsTable, RawPersonsTable)):
        return PropertyScope.PERSON
    if isinstance(resolved_table, GroupsTable):
        return PropertyScope.GROUP
    return PropertyScope.UNKNOWN


def _group_property_name(property_type: ast.PropertyType, context: HogQLContext, property_name: str) -> str | None:
    table_type = _unwrap_table_type(property_type.field_type.table_type)
    if isinstance(table_type, ast.LazyJoinType) and table_type.field.startswith("group_"):
        group_id = int(table_type.field.split("_")[1])
        return f"{group_id}_{property_name}"
    if isinstance(table_type, ast.LazyTableType):
        global_group_id: Optional[int] = context.globals.get("group_id") if context.globals else None
        if isinstance(global_group_id, int):
            return f"{global_group_id}_{property_name}"
    return None


def _constant_type_from_expr(expr: ast.Expr, context: HogQLContext) -> ast.ConstantType:
    expr_type = _resolve_expr_type(_unwrap_alias(expr))
    if expr_type is not None:
        return expr_type.resolve_constant_type(context)
    return ast.UnknownType()


def _resolve_expr_type(expr: ast.Expr) -> ast.Type | None:
    expr_type = expr.type
    while isinstance(expr_type, ast.FieldAliasType):
        expr_type = expr_type.type
    if isinstance(expr_type, ast.CallType):
        return dataclasses.replace(expr_type.return_type)
    return expr_type


def _unwrap_alias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr
