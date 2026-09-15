from __future__ import annotations

from collections.abc import Mapping
from dataclasses import field
from types import MappingProxyType
from typing import Any

from posthog.schema import HogQLFilters, HogQLQueryModifiers, HogQLVariable

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    ExpressionField,
    FieldTraverser,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    TableNode,
    UnknownDatabaseField,
    VirtualTable,
)
from posthog.hogql.database.trino_locator import TrinoTableLocator
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer.utils import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.schema_enums import DatabaseSerializedFieldType, PersonsOnEventsMode
from posthog.week_start_day import WeekStartDay


@frozen
class TrinoManifestColumn:
    name: str
    type: DatabaseSerializedFieldType
    nullable: bool = True


@frozen
class TrinoManifestTable:
    logical_name: str
    locator: TrinoTableLocator
    columns: tuple[TrinoManifestColumn, ...] = ()


@frozen
class TrinoCatalogManifest:
    tables: tuple[TrinoManifestTable, ...]
    timezone: str = "UTC"
    week_start_day: WeekStartDay = WeekStartDay.SUNDAY


@frozen
class TrinoManifestTranspilerResult:
    sql: str
    values: dict[str, Any]
    hogql: str | None = None
    print_columns: tuple[str, ...] = ()


@frozen
class PreparedTrinoCatalog:
    """A reusable catalog snapshot that creates fresh query state for every transpilation."""

    manifest: TrinoCatalogManifest
    _database: Database = field(repr=False, compare=False)
    _table_locators: Mapping[str, TrinoTableLocator] = field(repr=False, compare=False)

    def transpile(
        self,
        query: str | ast.SelectQuery | ast.SelectSetQuery,
        *,
        values: Mapping[str, object] | None = None,
        filters: HogQLFilters | None = None,
        variables: Mapping[str, HogQLVariable] | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        convert_to_project_timezone: bool | None = None,
        limit_top_select: bool = True,
        limit_context: LimitContext | None = None,
        default_limit: int | None = None,
        pretty: bool = False,
        include_hogql: bool = False,
    ) -> TrinoManifestTranspilerResult:
        return transpile_hogql_to_trino_with_database(
            query,
            database=self._database,
            locators=self._table_locators,
            values=values,
            filters=filters,
            variables=variables,
            modifiers=modifiers,
            convert_to_project_timezone=convert_to_project_timezone,
            limit_top_select=limit_top_select,
            limit_context=limit_context,
            default_limit=default_limit,
            pretty=pretty,
            include_hogql=include_hogql,
        )


_CORE_TABLES = frozenset({"events", "persons"})
_SUPPORTED_PURE_MODIFIERS = frozenset({"personsOnEventsMode", "convertToProjectTimezone"})
_FIELD_TYPES: dict[DatabaseSerializedFieldType, type[DatabaseField]] = {
    DatabaseSerializedFieldType.INTEGER: IntegerDatabaseField,
    DatabaseSerializedFieldType.FLOAT: FloatDatabaseField,
    DatabaseSerializedFieldType.DECIMAL: DecimalDatabaseField,
    DatabaseSerializedFieldType.STRING: StringDatabaseField,
    DatabaseSerializedFieldType.DATETIME: DateTimeDatabaseField,
    DatabaseSerializedFieldType.DATE: DateDatabaseField,
    DatabaseSerializedFieldType.BOOLEAN: BooleanDatabaseField,
    DatabaseSerializedFieldType.ARRAY: StringArrayDatabaseField,
    DatabaseSerializedFieldType.JSON: StringJSONDatabaseField,
    DatabaseSerializedFieldType.UNKNOWN: UnknownDatabaseField,
}


class _UnsupportedSemanticFeatureFinder(TraversingVisitor):
    def visit_call(self, node: ast.Call) -> None:
        if node.name == "matchesAction":
            raise TrinoLoweringError(
                "TRINO_PURE_ACTION_UNSUPPORTED",
                "action expansion",
                node,
                detail="Action references require Django semantic expansion.",
            )
        super().visit_call(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.InCohort, ast.CompareOperationOp.NotInCohort):
            raise TrinoLoweringError(
                "TRINO_PURE_COHORT_UNSUPPORTED",
                "cohort expansion",
                node,
                detail="Cohort references require Django semantic expansion.",
            )
        super().visit_compare_operation(node)


def _manifest_field(column: TrinoManifestColumn) -> DatabaseField:
    field_class = _FIELD_TYPES.get(column.type)
    if field_class is None:
        raise TrinoLoweringError(
            "TRINO_PURE_COLUMN_TYPE_UNSUPPORTED",
            "manifest column type",
            detail=f"Manifest column `{column.name}` uses unsupported type `{column.type.value}`.",
        )
    if not column.name:
        raise TrinoLoweringError(
            "TRINO_PURE_INVALID_MANIFEST",
            "manifest column",
            detail="Manifest column names must not be empty.",
        )
    return field_class(name=column.name, nullable=column.nullable)


def _configure_events_for_trino(database: Database) -> None:
    events = database.get_table("events")
    events.fields["person"] = FieldTraverser(chain=["poe"])
    events.fields["person_id"] = ExpressionField(
        name="person_id",
        expr=parse_expr("if(not(empty(override.distinct_id)), override.person_id, event_person_id)"),
        isolate_scope=True,
    )
    poe = events.fields["poe"]
    if not isinstance(poe, VirtualTable):
        raise TrinoLoweringError(
            "TRINO_PURE_INVALID_CORE_SCHEMA",
            "events table",
            detail="The fixed events definition does not expose its person-on-events fields.",
        )
    poe.fields["id"] = events.fields["person_id"]


def build_trino_manifest_database(manifest: TrinoCatalogManifest) -> tuple[Database, dict[str, TrinoTableLocator]]:
    database = Database(
        timezone=manifest.timezone,
        week_start_day=manifest.week_start_day,
        include_posthog_tables=True,
    )
    logical_names = [table.logical_name for table in manifest.tables]
    if len(logical_names) != len(set(logical_names)):
        raise TrinoLoweringError(
            "TRINO_PURE_INVALID_MANIFEST",
            "manifest tables",
            detail="Manifest logical table names must be unique.",
        )

    core_tables = set(_CORE_TABLES.intersection(logical_names))
    database.prune_to_table_names(core_tables)
    if "events" in core_tables:
        _configure_events_for_trino(database)

    locators: dict[str, TrinoTableLocator] = {}
    for table in manifest.tables:
        chain = table.logical_name.split(".")
        if not table.logical_name or any(not part for part in chain):
            raise TrinoLoweringError(
                "TRINO_PURE_INVALID_MANIFEST",
                "manifest table",
                detail=f"Invalid logical table name `{table.logical_name}`.",
            )
        if any(not value.strip() for value in table.locator):
            raise TrinoLoweringError(
                "TRINO_PURE_INVALID_MANIFEST",
                "manifest table locator",
                detail=f"Manifest table `{table.logical_name}` has an empty physical locator component.",
            )

        locators[table.logical_name] = table.locator
        if table.logical_name in _CORE_TABLES:
            if table.columns:
                raise TrinoLoweringError(
                    "TRINO_PURE_INVALID_MANIFEST",
                    "core table manifest",
                    detail=f"Core table `{table.logical_name}` uses its fixed schema and cannot declare columns.",
                )
            database.tables.get_child(chain).case_insensitive = True
            continue

        columns = {column.name: _manifest_field(column) for column in table.columns}
        if not columns or len(columns) != len(table.columns):
            raise TrinoLoweringError(
                "TRINO_PURE_INVALID_MANIFEST",
                "manifest columns",
                detail=f"Manifest table `{table.logical_name}` must declare unique columns.",
            )
        direct_table = DirectTrinoTable(
            name=chain[-1],
            fields=columns,
            has_complete_columns=True,
            external_data_source_id="",
            trino_catalog=table.locator[0],
            trino_schema=table.locator[1],
            trino_table_name=table.locator[2],
        )
        database.tables.add_child(
            TableNode.create_nested_for_chain(chain, direct_table, case_insensitive=True),
            table_conflict_mode="override",
        )

    return database, locators


def find_unsupported_pure_trino_features(node: ast.AST) -> None:
    """Raise the pure compiler's error for constructs Trino execution can never compile."""
    _UnsupportedSemanticFeatureFinder().visit(node)


def _validate_pure_inputs(
    *,
    filters: HogQLFilters | None,
    variables: Mapping[str, HogQLVariable] | None,
    modifiers: HogQLQueryModifiers | None,
) -> None:
    # Dashboards and URL-opened editor tabs send an empty filters object even when no filter is
    # set, so gate on content rather than presence.
    if filters is not None and filters.model_dump(exclude_none=True):
        raise TrinoLoweringError(
            "TRINO_PURE_FILTERS_UNSUPPORTED",
            "query filters",
            detail="Query filters require Django semantic expansion.",
        )
    if variables:
        raise TrinoLoweringError(
            "TRINO_PURE_VARIABLES_UNSUPPORTED",
            "query variables",
            detail="Query variables require Django semantic expansion.",
        )
    if modifiers is None:
        return

    # model_fields_set counts fields a serialize/validate round trip carried as explicit nulls,
    # so gate on values rather than key presence.
    set_modifiers = {key for key in modifiers.model_fields_set if getattr(modifiers, key) is not None}
    unsupported_modifiers = set_modifiers - _SUPPORTED_PURE_MODIFIERS
    if unsupported_modifiers:
        unsupported = ", ".join(sorted(unsupported_modifiers))
        raise TrinoLoweringError(
            "TRINO_PURE_MODIFIER_UNSUPPORTED",
            "query modifier",
            detail=f"Pure Trino transpilation does not support these modifiers: {unsupported}.",
        )
    persons_mode = modifiers.personsOnEventsMode
    if persons_mode is not None and persons_mode != PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
        raise TrinoLoweringError(
            "TRINO_PERSONS_ON_EVENTS_MODE_UNSUPPORTED",
            f"personsOnEventsMode={persons_mode.value}",
            detail="Trino compilation supports only personsOnEventsMode=person_id_override_properties_on_events.",
        )


def prepare_trino_catalog(manifest: TrinoCatalogManifest) -> PreparedTrinoCatalog:
    database, table_locators = build_trino_manifest_database(manifest)
    return PreparedTrinoCatalog(
        manifest=manifest,
        _database=database,
        _table_locators=MappingProxyType(table_locators),
    )


def transpile_hogql_to_trino(
    query: str | ast.SelectQuery | ast.SelectSetQuery,
    *,
    manifest: TrinoCatalogManifest,
    values: Mapping[str, object] | None = None,
    filters: HogQLFilters | None = None,
    variables: Mapping[str, HogQLVariable] | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    convert_to_project_timezone: bool | None = None,
    limit_top_select: bool = True,
    limit_context: LimitContext | None = None,
    default_limit: int | None = None,
    pretty: bool = False,
    include_hogql: bool = False,
) -> TrinoManifestTranspilerResult:
    return prepare_trino_catalog(manifest).transpile(
        query,
        values=values,
        filters=filters,
        variables=variables,
        modifiers=modifiers,
        convert_to_project_timezone=convert_to_project_timezone,
        limit_top_select=limit_top_select,
        limit_context=limit_context,
        default_limit=default_limit,
        pretty=pretty,
        include_hogql=include_hogql,
    )


def transpile_hogql_to_trino_with_database(
    query: str | ast.SelectQuery | ast.SelectSetQuery,
    *,
    database: Database,
    locators: Mapping[str, TrinoTableLocator] | None = None,
    values: Mapping[str, object] | None = None,
    filters: HogQLFilters | None = None,
    variables: Mapping[str, HogQLVariable] | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    convert_to_project_timezone: bool | None = None,
    limit_top_select: bool = True,
    limit_context: LimitContext | None = None,
    default_limit: int | None = None,
    pretty: bool = False,
    include_hogql: bool = False,
) -> TrinoManifestTranspilerResult:
    """Transpile against an already-built database, such as a connection-scoped one.

    A DirectTrinoTable carries its own physical locator, so ``locators`` is only needed for
    tables that do not, such as the managed core tables.
    """
    _validate_pure_inputs(filters=filters, variables=variables, modifiers=modifiers)
    placeholders: dict[str, ast.Expr] | None = (
        {key: ast.Constant(value=value) for key, value in values.items()} if values else None
    )
    node = parse_select(query, placeholders=placeholders) if isinstance(query, str) else clone_expr(query, True)
    if default_limit is not None:
        for select_query in extract_select_queries(node):
            if select_query.limit is None:
                select_query.limit = ast.Constant(value=default_limit)
    unsupported_placeholders = find_placeholders(node)
    if (
        unsupported_placeholders.has_filters
        or unsupported_placeholders.placeholder_fields
        or unsupported_placeholders.placeholder_expressions
    ):
        raise TrinoLoweringError(
            "TRINO_PURE_PLACEHOLDER_UNSUPPORTED",
            "unresolved placeholder",
            node,
            detail="Pure Trino transpilation only accepts constant values supplied by the caller.",
        )
    _UnsupportedSemanticFeatureFinder().visit(node)

    table_locators = locators if locators is not None else {}

    def create_context() -> HogQLContext:
        return HogQLContext(
            database=database,
            team_id=None,
            team=None,
            user=None,
            enable_select_queries=True,
            limit_top_select=limit_top_select,
            limit_context=limit_context,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                convertToProjectTimezone=(
                    modifiers.convertToProjectTimezone
                    if modifiers is not None and modifiers.convertToProjectTimezone is not None
                    else convert_to_project_timezone
                ),
            ),
            restricted_properties=set(),
            trino_table_locators=table_locators,
            timezone=database.get_timezone(),
            week_start_day=database.get_week_start_day(),
        )

    context = create_context()
    hogql: str | None = None
    print_columns: list[str] = []
    if include_hogql:
        hogql_context = create_context()
        hogql, prepared_hogql = prepare_and_print_ast(clone_expr(node), hogql_context, dialect="hogql")
        if isinstance(prepared_hogql, ast.SelectQuery | ast.SelectSetQuery):
            columns_query = (
                next(extract_select_queries(prepared_hogql))
                if isinstance(prepared_hogql, ast.SelectSetQuery)
                else prepared_hogql
            )
            for select_node in columns_query.select:
                if isinstance(select_node, ast.Alias):
                    print_columns.append(select_node.alias)
                else:
                    stack = [prepared_hogql] if isinstance(prepared_hogql, ast.SelectQuery) else None
                    print_columns.append(
                        print_prepared_ast(node=select_node, context=hogql_context, dialect="hogql", stack=stack)
                    )
    sql, _ = prepare_and_print_ast(node, context, dialect="trino", pretty=pretty)
    return TrinoManifestTranspilerResult(
        sql=sql, values=dict(context.values), hogql=hogql, print_columns=tuple(print_columns)
    )
