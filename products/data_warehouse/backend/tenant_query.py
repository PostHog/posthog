from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from time import perf_counter
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import BooleanDatabaseField, FieldOrTable, StringDatabaseField, Table, TableNode
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.resolver import resolve_types
from posthog.hogql.resolver_utils import extract_base_table_types
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.tenant_query_config import DataWarehouseTenantQueryConfig

logger = structlog.get_logger(__name__)

DEFAULT_TENANT_QUERY_TIMEOUT_MS = 30_000
DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS = 120_000
DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT = 100_000
DEFAULT_TENANT_QUERY_OBSERVABILITY_LIMIT = 100
MAX_TENANT_QUERY_OBSERVABILITY_LIMIT = 1_000
TENANT_QUERY_LOG_EVENT = "tenant_query_execution"
TENANT_QUERY_RESPONSE_FIELDS = {
    "columns",
    "error",
    "hasMore",
    "hogql",
    "limit",
    "offset",
    "postgres_sql",
    "query",
    "results",
    "timings",
    "types",
}

SUPPORTED_POSTGRES_INTEGER_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "int",
    "int2",
    "int4",
    "int8",
    "smallserial",
    "serial",
    "bigserial",
    "serial2",
    "serial4",
    "serial8",
}
SUPPORTED_POSTGRES_STRING_TYPES = {
    "character",
    "character varying",
    "char",
    "citext",
    "name",
    "text",
    "varchar",
    "bpchar",
}
SUPPORTED_POSTGRES_UUID_TYPES = {"uuid"}
TENANT_METADATA_TABLE_ALIASES = {
    ("system", "tables"): "tables",
    ("system", "fields"): "fields",
}
TENANT_METADATA_COLUMNS = {
    "tables": ["name", "source_schema", "source_table_name"],
    "fields": ["table", "name", "postgres_type", "nullable"],
}
TENANT_METADATA_COLUMN_TYPES = {
    "name": "string",
    "nullable": "boolean",
    "postgres_type": "string",
    "source_schema": "string",
    "source_table_name": "string",
    "table": "string",
}

TenantColumnNamesByTable = dict[str, str]


def _get_direct_postgres_source(team: Team, connection_id: str) -> ExternalDataSource:
    try:
        source = ExternalDataSource.objects.exclude(deleted=True).get(team_id=team.pk, id=connection_id)
    except ExternalDataSource.DoesNotExist as error:
        raise ExposedHogQLError("Direct Postgres connection not found.") from error

    if not source.is_direct_postgres:
        raise ExposedHogQLError("Tenant query service requires a direct Postgres connection.")

    return source


def _direct_postgres_schemas(source: ExternalDataSource) -> list[ExternalDataSchema]:
    return list(
        ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id)
        .exclude(deleted=True)
        .filter(table_id__isnull=False)
        .select_related("table")
    )


def _enabled_direct_postgres_schemas(source: ExternalDataSource) -> list[ExternalDataSchema]:
    return [schema for schema in _direct_postgres_schemas(source) if schema.should_sync]


def _schema_display_name(schema: ExternalDataSchema) -> str:
    if schema.table is not None:
        return schema.table.name
    return schema.name


def _enabled_table_names(source: ExternalDataSource) -> list[str]:
    schemas = _enabled_direct_postgres_schemas(source)
    omit_source_schema = _enabled_schemas_use_single_source_schema(schemas)
    return sorted(_tenant_query_table_name(schema, omit_source_schema=omit_source_schema) for schema in schemas)


def _postgres_schema_columns(schema: ExternalDataSchema) -> list[dict[str, object]]:
    metadata = schema.schema_metadata
    columns = metadata.get("columns") if metadata else None
    if not isinstance(columns, list):
        raise ExposedHogQLError(
            f"Direct Postgres schema metadata is missing for `{_schema_display_name(schema)}`. "
            "Refresh the connection schema before enabling tenant queries."
        )

    postgres_columns: list[dict[str, object]] = []
    for column in columns:
        if isinstance(column, dict):
            postgres_columns.append({str(key): value for key, value in column.items()})
    return postgres_columns


def _postgres_schema_column(schema: ExternalDataSchema, column_name: str) -> dict[str, object] | None:
    return next((column for column in _postgres_schema_columns(schema) if column.get("name") == column_name), None)


def _schema_metadata_value(schema: ExternalDataSchema, key: str) -> str | None:
    metadata = schema.schema_metadata
    if metadata is None:
        return None
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _schema_source_schema_name(schema: ExternalDataSchema) -> str | None:
    source_schema = _schema_metadata_value(schema, "source_schema")
    if source_schema:
        return source_schema

    display_name = _schema_display_name(schema)
    if "." in display_name:
        return display_name.split(".", maxsplit=1)[0]

    return None


def _schema_source_table_name(schema: ExternalDataSchema) -> str:
    source_table_name = _schema_metadata_value(schema, "source_table_name")
    if source_table_name:
        return source_table_name

    display_name = _schema_display_name(schema)
    if "." in display_name:
        return display_name.split(".", maxsplit=1)[1]

    return display_name


def _enabled_schemas_use_single_source_schema(schemas: list[ExternalDataSchema]) -> bool:
    source_schema_names = {
        source_schema_name
        for schema in schemas
        if (source_schema_name := _schema_source_schema_name(schema)) is not None
    }
    return len(source_schema_names) == 1


def _tenant_query_table_name(schema: ExternalDataSchema, *, omit_source_schema: bool) -> str:
    return _schema_source_table_name(schema) if omit_source_schema else _schema_display_name(schema)


def _normalize_postgres_type(postgres_type: str) -> str:
    normalized_type = " ".join(postgres_type.strip().lower().split())
    return normalized_type.split("(", maxsplit=1)[0].strip()


def _tenant_column_type_from_postgres(postgres_type: str) -> str:
    normalized_type = _normalize_postgres_type(postgres_type)
    if normalized_type in SUPPORTED_POSTGRES_INTEGER_TYPES:
        return DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
    if normalized_type in SUPPORTED_POSTGRES_UUID_TYPES:
        return DataWarehouseTenantQueryConfig.TenantColumnType.UUID
    if normalized_type in SUPPORTED_POSTGRES_STRING_TYPES:
        return DataWarehouseTenantQueryConfig.TenantColumnType.STRING
    raise ExposedHogQLError(
        f"Tenant column Postgres type `{postgres_type}` is not supported. "
        "Supported tenant column types are integer, string, and uuid."
    )


def _tenant_column_type_for_schema_column(schema: ExternalDataSchema, column_name: str) -> str | None:
    column = _postgres_schema_column(schema, column_name)
    if column is None:
        return None

    postgres_type = column.get("data_type")
    if not isinstance(postgres_type, str):
        raise ExposedHogQLError(f"Unable to infer tenant column type for table `{_schema_display_name(schema)}`.")
    return _tenant_column_type_from_postgres(postgres_type)


def _infer_tenant_column_type_from_schemas(schemas: list[ExternalDataSchema], tenant_column_name: str) -> str | None:
    inferred_types: set[str] = set()

    for schema in schemas:
        tenant_column_type = _tenant_column_type_for_schema_column(schema, tenant_column_name)
        if tenant_column_type is None:
            continue
        inferred_types.add(tenant_column_type)

    if len(inferred_types) > 1:
        type_list = ", ".join(sorted(inferred_types))
        raise ExposedHogQLError(f"Tenant column `{tenant_column_name}` has inconsistent types: {type_list}.")

    return next(iter(inferred_types)) if inferred_types else None


def infer_tenant_column_type(source: ExternalDataSource, tenant_column_name: str) -> str:
    if not source.is_direct_postgres:
        raise ExposedHogQLError("Tenant query service requires a direct Postgres connection.")

    schemas = _enabled_direct_postgres_schemas(source)
    if not schemas:
        raise ExposedHogQLError("Tenant query service requires at least one enabled table.")

    missing_table_names: list[str] = []

    for schema in schemas:
        if _postgres_schema_column(schema, tenant_column_name) is None:
            missing_table_names.append(_schema_display_name(schema))

    if missing_table_names:
        table_list = ", ".join(sorted(missing_table_names))
        raise ExposedHogQLError(f"Tenant column `{tenant_column_name}` is missing from enabled tables: {table_list}.")

    tenant_column_type = _infer_tenant_column_type_from_schemas(schemas, tenant_column_name)
    if tenant_column_type is None:
        raise ExposedHogQLError(f"Tenant column `{tenant_column_name}` was not found on any enabled table.")

    return tenant_column_type


def _tenant_column_overrides(
    config: DataWarehouseTenantQueryConfig | None,
) -> TenantColumnNamesByTable:
    if config is None or not isinstance(config.tenant_column_names_by_table, dict):
        return {}

    return {
        str(table_name): str(column_name)
        for table_name, column_name in config.tenant_column_names_by_table.items()
        if str(table_name).strip() and str(column_name).strip()
    }


def _schema_lookup_names(schema: ExternalDataSchema) -> set[str]:
    source_schema_name = _schema_source_schema_name(schema)
    source_table_name = _schema_source_table_name(schema)
    names = {_schema_display_name(schema), source_table_name}
    if source_schema_name is not None:
        names.add(f"{source_schema_name}.{source_table_name}")
    return names


def _schema_by_tenant_column_override_key(schemas: list[ExternalDataSchema]) -> dict[str, ExternalDataSchema]:
    schema_by_name: dict[str, ExternalDataSchema] = {}
    name_counts: dict[str, int] = {}

    for schema in schemas:
        for name in _schema_lookup_names(schema):
            name_counts[name] = name_counts.get(name, 0) + 1
            schema_by_name[name] = schema

    return {name: schema for name, schema in schema_by_name.items() if name_counts[name] == 1}


def _canonical_tenant_column_overrides(
    schemas: list[ExternalDataSchema],
    tenant_column_names_by_table: Mapping[str, object] | None,
    default_tenant_column_name: str,
) -> TenantColumnNamesByTable:
    if tenant_column_names_by_table is None:
        return {}

    schema_by_name = _schema_by_tenant_column_override_key(schemas)
    overrides: TenantColumnNamesByTable = {}
    for table_name, column_name in tenant_column_names_by_table.items():
        normalized_table_name = str(table_name).strip()
        normalized_column_name = str(column_name).strip()
        if not normalized_table_name or not normalized_column_name:
            continue

        schema = schema_by_name.get(normalized_table_name)
        if schema is None:
            continue

        if normalized_column_name == default_tenant_column_name:
            continue

        overrides[_schema_display_name(schema)] = normalized_column_name

    return dict(sorted(overrides.items()))


def _tenant_column_type_for_effective_columns(
    schemas: list[ExternalDataSchema],
    default_tenant_column_name: str,
    tenant_column_names_by_table: TenantColumnNamesByTable,
    existing_tenant_column_type: str | None,
) -> str:
    candidate_types: set[str] = set()
    for schema in schemas:
        if _schema_display_name(schema) in tenant_column_names_by_table:
            continue

        tenant_column_type = _tenant_column_type_for_schema_column(schema, default_tenant_column_name)
        if tenant_column_type is not None:
            candidate_types.add(tenant_column_type)

    if not candidate_types:
        for schema in schemas:
            tenant_column_type = _tenant_column_type_for_schema_column(schema, default_tenant_column_name)
            if tenant_column_type is not None:
                candidate_types.add(tenant_column_type)

    if len(candidate_types) > 1:
        type_list = ", ".join(sorted(candidate_types))
        raise ExposedHogQLError(f"Tenant column `{default_tenant_column_name}` has inconsistent types: {type_list}.")

    if candidate_types:
        return next(iter(candidate_types))

    return existing_tenant_column_type or DataWarehouseTenantQueryConfig.TenantColumnType.STRING


def _validate_tenant_column_overrides(
    schemas: list[ExternalDataSchema],
    tenant_column_names_by_table: TenantColumnNamesByTable,
    tenant_column_type: str,
) -> TenantColumnNamesByTable:
    schema_by_name = {_schema_display_name(schema): schema for schema in schemas}
    validated_overrides: TenantColumnNamesByTable = {}

    for table_name, tenant_column_name in tenant_column_names_by_table.items():
        schema = schema_by_name.get(table_name)
        if schema is None:
            continue

        override_type = _tenant_column_type_for_schema_column(schema, tenant_column_name)
        if override_type is None:
            raise ExposedHogQLError(
                f"Tenant column `{tenant_column_name}` is missing from table `{_schema_display_name(schema)}`."
            )
        if override_type != tenant_column_type:
            raise ExposedHogQLError(
                f"Tenant column `{tenant_column_name}` on table `{_schema_display_name(schema)}` has type "
                f"`{override_type}`, but the global tenant column type is `{tenant_column_type}`."
            )

        validated_overrides[table_name] = tenant_column_name

    return dict(sorted(validated_overrides.items()))


def _tenant_column_name_for_schema(
    schema: ExternalDataSchema,
    config: DataWarehouseTenantQueryConfig,
) -> str:
    return _tenant_column_overrides(config).get(_schema_display_name(schema), config.tenant_column_name)


def _tenant_column_name_for_direct_postgres_table(
    table: DirectPostgresTable,
    config: DataWarehouseTenantQueryConfig,
) -> str:
    overrides = _tenant_column_overrides(config)
    direct_table_names = [
        table.to_printed_hogql(),
        f"{table.postgres_schema}.{table.postgres_table_name}",
        table.postgres_table_name,
    ]

    for table_name in direct_table_names:
        tenant_column_name = overrides.get(table_name)
        if tenant_column_name is not None:
            return tenant_column_name

    return config.tenant_column_name


def _tenant_column_output_names(config: DataWarehouseTenantQueryConfig) -> set[str]:
    return {config.tenant_column_name, *_tenant_column_overrides(config).values()}


def _disable_schemas_without_tenant_column(source: ExternalDataSource, schemas: list[ExternalDataSchema]) -> list[str]:
    schema_ids: list[UUID] = []
    table_names: list[str] = []

    for schema in schemas:
        schema_ids.append(schema.id)
        table_names.append(_schema_display_name(schema))

    if schema_ids:
        ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, id__in=schema_ids).update(
            should_sync=False
        )

    return sorted(table_names)


def _tenant_metadata_table_rows(source: ExternalDataSource) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    schemas = _enabled_direct_postgres_schemas(source)
    omit_source_schema = _enabled_schemas_use_single_source_schema(schemas)
    for schema in schemas:
        rows.append(
            {
                "name": _tenant_query_table_name(schema, omit_source_schema=omit_source_schema),
                "source_schema": _schema_metadata_value(schema, "source_schema") or "public",
                "source_table_name": _schema_metadata_value(schema, "source_table_name") or schema.name,
            }
        )
    return rows


def _tenant_metadata_field_rows(
    source: ExternalDataSource,
    config: DataWarehouseTenantQueryConfig,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    schemas = _enabled_direct_postgres_schemas(source)
    omit_source_schema = _enabled_schemas_use_single_source_schema(schemas)
    for schema in schemas:
        table_name = _tenant_query_table_name(schema, omit_source_schema=omit_source_schema)
        tenant_column_name = _tenant_column_name_for_schema(schema, config)
        for column in _postgres_schema_columns(schema):
            column_name = column.get("name")
            postgres_type = column.get("data_type")
            if not isinstance(column_name, str) or not isinstance(postgres_type, str):
                continue
            if column_name == tenant_column_name:
                continue

            rows.append(
                {
                    "table": table_name,
                    "name": column_name,
                    "postgres_type": postgres_type,
                    "nullable": bool(column.get("is_nullable")),
                }
            )
    return rows


def _metadata_table_name(select_query: ast.SelectQuery) -> str | None:
    join_expr = select_query.select_from
    if join_expr is None or join_expr.next_join is not None:
        return None
    if not isinstance(join_expr.table, ast.Field):
        return None

    chain = tuple(str(part) for part in join_expr.table.chain)
    return TENANT_METADATA_TABLE_ALIASES.get(chain)


def _metadata_limit(select_query: ast.SelectQuery, max_result_limit: int) -> int:
    if select_query.limit is None:
        return min(100, max_result_limit)
    if not isinstance(select_query.limit, ast.Constant) or not isinstance(select_query.limit.value, int):
        raise ExposedHogQLError("Tenant metadata queries only support integer LIMIT values.")
    return min(select_query.limit.value, max_result_limit)


def _metadata_offset(select_query: ast.SelectQuery) -> int:
    if select_query.offset is None:
        return 0
    if not isinstance(select_query.offset, ast.Constant) or not isinstance(select_query.offset.value, int):
        raise ExposedHogQLError("Tenant metadata queries only support integer OFFSET values.")
    return select_query.offset.value


def _metadata_filter_matches(row: dict[str, object], expr: ast.Expr | None) -> bool:
    if expr is None:
        return True
    if isinstance(expr, ast.And):
        return all(_metadata_filter_matches(row, child_expr) for child_expr in expr.exprs)
    if isinstance(expr, ast.CompareOperation) and expr.op == ast.CompareOperationOp.Eq:
        left = expr.left.expr if isinstance(expr.left, ast.Alias) else expr.left
        right = expr.right.expr if isinstance(expr.right, ast.Alias) else expr.right
        if isinstance(left, ast.Field) and isinstance(right, ast.Constant) and left.chain:
            return row.get(str(left.chain[-1])) == right.value
        if isinstance(right, ast.Field) and isinstance(left, ast.Constant) and right.chain:
            return row.get(str(right.chain[-1])) == left.value
    raise ExposedHogQLError("Tenant metadata queries only support equality filters joined with AND.")


def _tenant_metadata_database_field(name: str, metadata_type: str) -> FieldOrTable:
    if metadata_type == "boolean":
        return BooleanDatabaseField(name=name)
    return StringDatabaseField(name=name)


def _tenant_metadata_database() -> Database:
    database = Database(include_posthog_tables=False)
    system_node = TableNode(
        name="system",
        children={
            table_name: TableNode(
                name=table_name,
                table=Table(
                    name=f"system.{table_name}",
                    fields={
                        column: _tenant_metadata_database_field(column, TENANT_METADATA_COLUMN_TYPES[column])
                        for column in columns
                    },
                ),
            )
            for table_name, columns in TENANT_METADATA_COLUMNS.items()
        },
    )
    database.tables.add_child(system_node)
    return database


def _metadata_query_references_table(node: ast.SelectQuery | ast.SelectSetQuery | ast.JoinExpr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.SelectSetQuery):
        return _metadata_query_references_table(node.initial_select_query) or any(
            _metadata_query_references_table(select_node.select_query) for select_node in node.subsequent_select_queries
        )
    if isinstance(node, ast.SelectQuery):
        return any(_metadata_query_references_table(cte.expr) for cte in (node.ctes or {}).values()) or (
            _metadata_query_references_table(node.select_from)
        )

    if isinstance(node.table, ast.Field):
        if TENANT_METADATA_TABLE_ALIASES.get(tuple(str(part) for part in node.table.chain)) is not None:
            return True
    elif isinstance(node.table, ast.SelectQuery | ast.SelectSetQuery):
        return _metadata_query_references_table(node.table)

    return _metadata_query_references_table(node.next_join)


def _tenant_metadata_base_rows(
    source: ExternalDataSource,
    config: DataWarehouseTenantQueryConfig,
) -> dict[str, tuple[list[dict[str, object]], dict[str, str]]]:
    return {
        "tables": (
            _tenant_metadata_table_rows(source),
            {column: TENANT_METADATA_COLUMN_TYPES[column] for column in TENANT_METADATA_COLUMNS["tables"]},
        ),
        "fields": (
            _tenant_metadata_field_rows(source, config),
            {column: TENANT_METADATA_COLUMN_TYPES[column] for column in TENANT_METADATA_COLUMNS["fields"]},
        ),
    }


def _metadata_source_rows(
    join_expr: ast.JoinExpr | None,
    base_rows: dict[str, tuple[list[dict[str, object]], dict[str, str]]],
    ctes: dict[str, tuple[list[dict[str, object]], dict[str, str]]],
    max_result_limit: int,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    if join_expr is None:
        return [{}], {}
    if join_expr.next_join is not None:
        raise ExposedHogQLError("Tenant metadata queries do not support joins.")

    table = join_expr.table
    if isinstance(table, ast.Field):
        table_chain = tuple(str(part) for part in table.chain)
        cte_name = ".".join(table_chain)
        if cte_name in ctes:
            return ctes[cte_name]

        table_name = TENANT_METADATA_TABLE_ALIASES.get(table_chain)
        if table_name is None:
            raise ExposedHogQLError(f"Unknown tenant metadata table `{cte_name}`.")
        return base_rows[table_name]

    if isinstance(table, ast.SelectQuery):
        rows, column_types, _has_more, _offset, _limit = _evaluate_tenant_metadata_select(
            table, base_rows, max_result_limit, ctes
        )
        return rows, column_types

    raise ExposedHogQLError("Tenant metadata queries only support metadata tables and subqueries.")


def _metadata_selected_column(
    expr: ast.Expr,
    input_column_types: dict[str, str],
) -> tuple[str, str, str]:
    alias: str | None = None
    if isinstance(expr, ast.Alias):
        alias = expr.alias
        expr = expr.expr

    if not isinstance(expr, ast.Field) or not expr.chain:
        raise ExposedHogQLError("Tenant metadata queries only support selecting metadata columns.")

    column_name = str(expr.chain[-1])
    if column_name not in input_column_types:
        raise ExposedHogQLError(f"Unknown tenant metadata column `{column_name}`.")
    return column_name, alias or column_name, input_column_types[column_name]


def _metadata_order_key(row: dict[str, object], order_expr: ast.OrderExpr) -> object:
    if not isinstance(order_expr.expr, ast.Field) or not order_expr.expr.chain:
        raise ExposedHogQLError("Tenant metadata queries only support ordering by metadata columns.")
    return row.get(str(order_expr.expr.chain[-1]))


def _evaluate_tenant_metadata_select(
    select_query: ast.SelectQuery,
    base_rows: dict[str, tuple[list[dict[str, object]], dict[str, str]]],
    max_result_limit: int,
    ctes: dict[str, tuple[list[dict[str, object]], dict[str, str]]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, str], bool, int, int]:
    if (
        select_query.distinct
        or select_query.array_join_list
        or select_query.group_by
        or select_query.having
        or select_query.qualify
        or select_query.window_exprs
    ):
        raise ExposedHogQLError("Tenant metadata queries only support simple SELECT queries.")

    resolved_ctes = dict(ctes or {})
    for cte_name, cte in (select_query.ctes or {}).items():
        if not isinstance(cte.expr, ast.SelectQuery):
            raise ExposedHogQLError("Tenant metadata CTEs only support SELECT queries.")
        cte_rows, cte_column_types, _has_more, _offset, _limit = _evaluate_tenant_metadata_select(
            cte.expr, base_rows, max_result_limit, resolved_ctes
        )
        resolved_ctes[cte_name] = (cte_rows, cte_column_types)

    source_rows, source_column_types = _metadata_source_rows(
        select_query.select_from, base_rows, resolved_ctes, max_result_limit
    )
    rows = [row for row in source_rows if _metadata_filter_matches(row, select_query.where)]

    for order_expr in reversed(select_query.order_by or []):
        rows = sorted(rows, key=lambda row: _metadata_order_key(row, order_expr), reverse=order_expr.order == "DESC")

    selected_columns = [_metadata_selected_column(expr, source_column_types) for expr in select_query.select]
    projected_rows = [
        {alias: row[column_name] for column_name, alias, _metadata_type in selected_columns} for row in rows
    ]
    projected_column_types = {alias: metadata_type for _column_name, alias, metadata_type in selected_columns}

    offset = _metadata_offset(select_query)
    limit = _metadata_limit(select_query, max_result_limit)
    page = projected_rows[offset : offset + limit]
    return page, projected_column_types, offset + limit < len(projected_rows), offset, limit


def execute_tenant_metadata_query(
    *,
    source: ExternalDataSource,
    config: DataWarehouseTenantQueryConfig,
    query: str,
) -> tuple[dict[str, object], int] | None:
    select_query = parse_select(query)
    if not isinstance(select_query, ast.SelectQuery):
        return None

    if not _metadata_query_references_table(select_query):
        return None

    resolved_query = resolve_types(
        select_query,
        HogQLContext(database=_tenant_metadata_database(), limit_top_select=False),
        "hogql",
    )
    if not isinstance(resolved_query, ast.SelectQuery):
        raise ExposedHogQLError("Tenant metadata queries only support SELECT queries.")

    page, column_types, has_more, offset, limit = _evaluate_tenant_metadata_select(
        resolved_query,
        _tenant_metadata_base_rows(source, config),
        config.max_result_limit or DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT,
    )

    columns = list(column_types.keys())
    return (
        {
            "query": query,
            "hogql": query,
            "columns": columns,
            "types": [[column, column_types[column]] for column in columns],
            "results": [[row[column] for column in columns] for row in page],
            "timings": [],
            "limit": limit,
            "offset": offset,
            "hasMore": has_more,
        },
        len(page),
    )


def _tenant_query_observability_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_TENANT_QUERY_OBSERVABILITY_LIMIT
    return max(1, min(limit, MAX_TENANT_QUERY_OBSERVABILITY_LIMIT))


def _tenant_query_observability_window(
    date_from: datetime | None,
    date_to: datetime | None,
    default_lookback: timedelta = timedelta(hours=24),
) -> tuple[datetime, datetime]:
    resolved_date_to = date_to or timezone.now()
    resolved_date_from = date_from or resolved_date_to - default_lookback
    if resolved_date_from > resolved_date_to:
        raise ExposedHogQLError("date_from must be earlier than date_to.")
    return resolved_date_from, resolved_date_to


def _tenant_query_logs_filter(
    *,
    date_from: datetime,
    date_to: datetime,
    connection_id: str | None = None,
    tenant_value: object | None = None,
    success: bool | None = None,
) -> ast.Expr:
    exprs: list[ast.Expr] = [
        parse_expr(
            "(body = {event_name} OR event_name = {event_name} OR JSONExtractString(attributes, 'event') = {event_name})",
            placeholders={"event_name": ast.Constant(value=TENANT_QUERY_LOG_EVENT)},
        ),
        parse_expr(
            "toStartOfDay(time_bucket) >= toStartOfDay({date_from}) AND toStartOfDay(time_bucket) <= toStartOfDay({date_to})",
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
            },
        ),
        parse_expr(
            "timestamp >= {date_from} AND timestamp <= {date_to}",
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
            },
        ),
    ]

    if connection_id is not None:
        exprs.append(
            parse_expr(
                "JSONExtractString(attributes, 'connection_id') = {connection_id}",
                placeholders={"connection_id": ast.Constant(value=str(connection_id))},
            )
        )
    if tenant_value is not None:
        exprs.append(
            parse_expr(
                "JSONExtractString(attributes, 'tenant_value') = {tenant_value}",
                placeholders={"tenant_value": ast.Constant(value=str(tenant_value))},
            )
        )
    if success is not None:
        exprs.append(
            parse_expr(
                "JSONExtractBool(attributes, 'success') = {success}",
                placeholders={"success": ast.Constant(value=success)},
            )
        )

    return ast.And(exprs=exprs)


def _execute_tenant_query_logs(team: Team, query: ast.SelectQuery) -> list[list[object]]:
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="TenantQueryLogs",
        limit_context=LimitContext.QUERY,
    )
    return response.results or []


def _serialize_log_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_log_json(value: object, default: object) -> object:
    if value is None or value == "":
        return default
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _parse_log_json_list(value: object) -> list[str]:
    parsed_value = _parse_log_json(value, [])
    if isinstance(parsed_value, list):
        return [str(item) for item in parsed_value]
    if parsed_value is None:
        return []
    return [str(parsed_value)]


def _parse_log_json_dict(value: object) -> dict[str, object]:
    parsed_value = _parse_log_json(value, {})
    if isinstance(parsed_value, dict):
        return {str(key): value for key, value in parsed_value.items()}
    return {}


def _tenant_query_log_row_to_execution(row: list[object]) -> dict[str, object | None]:
    return {
        "id": str(row[0]),
        "timestamp": _serialize_log_timestamp(row[1]),
        "connection_id": str(row[2]),
        "tenant_value": str(row[3]),
        "original_query": str(row[4]),
        "postgres_sql": str(row[5]) if row[5] else None,
        "success": bool(row[6]),
        "error": str(row[7]) if row[7] else None,
        "duration_ms": float(row[8]) if row[8] is not None else None,
        "row_count": int(row[9]) if row[9] is not None else None,
        "referenced_tables": _parse_log_json_list(row[10]),
        "metadata_only": bool(row[11]),
    }


def _tenant_query_log_row_to_execution_detail(row: list[object]) -> dict[str, object | None]:
    execution = _tenant_query_log_row_to_execution(row[:12])
    execution["referenced_table_metadata"] = _parse_log_json(row[12], [])
    execution["connection_metadata"] = _parse_log_json_dict(row[13])
    execution["attributes"] = _parse_log_json_dict(row[14])
    return execution


def list_tenant_query_executions(
    *,
    team: Team,
    connection_id: str | None = None,
    tenant_value: object | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    success: bool | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    resolved_date_from, resolved_date_to = _tenant_query_observability_window(date_from, date_to)
    resolved_limit = _tenant_query_observability_limit(limit)
    query = parse_select(
        """
        SELECT
            uuid,
            timestamp,
            JSONExtractString(attributes, 'connection_id') as connection_id,
            JSONExtractString(attributes, 'tenant_value') as tenant_value,
            JSONExtractString(attributes, 'original_query') as original_query,
            JSONExtractString(attributes, 'postgres_sql') as postgres_sql,
            JSONExtractBool(attributes, 'success') as success,
            JSONExtractString(attributes, 'error') as error,
            JSONExtractFloat(attributes, 'duration_ms') as duration_ms,
            JSONExtractInt(attributes, 'row_count') as row_count,
            JSONExtractRaw(attributes, 'referenced_tables') as referenced_tables,
            JSONExtractBool(attributes, 'metadata_only') as metadata_only
        FROM logs
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT {limit}
        """,
        placeholders={
            "where": _tenant_query_logs_filter(
                date_from=resolved_date_from,
                date_to=resolved_date_to,
                connection_id=connection_id,
                tenant_value=tenant_value,
                success=success,
            ),
            "limit": ast.Constant(value=resolved_limit),
        },
    )
    rows = _execute_tenant_query_logs(team, query)
    return {
        "executions": [_tenant_query_log_row_to_execution(row) for row in rows],
        "count": len(rows),
    }


def get_tenant_query_execution(
    *,
    team: Team,
    execution_id: str,
    timestamp: datetime | None = None,
) -> dict[str, object | None] | None:
    if timestamp is not None:
        resolved_date_from = timestamp - timedelta(minutes=5)
        resolved_date_to = timestamp + timedelta(minutes=5)
    else:
        resolved_date_from, resolved_date_to = _tenant_query_observability_window(
            None, None, default_lookback=timedelta(days=7)
        )

    where = parse_expr(
        "{base_filter} AND uuid = {execution_id}",
        placeholders={
            "base_filter": _tenant_query_logs_filter(date_from=resolved_date_from, date_to=resolved_date_to),
            "execution_id": ast.Constant(value=execution_id),
        },
    )
    query = parse_select(
        """
        SELECT
            uuid,
            timestamp,
            JSONExtractString(attributes, 'connection_id') as connection_id,
            JSONExtractString(attributes, 'tenant_value') as tenant_value,
            JSONExtractString(attributes, 'original_query') as original_query,
            JSONExtractString(attributes, 'postgres_sql') as postgres_sql,
            JSONExtractBool(attributes, 'success') as success,
            JSONExtractString(attributes, 'error') as error,
            JSONExtractFloat(attributes, 'duration_ms') as duration_ms,
            JSONExtractInt(attributes, 'row_count') as row_count,
            JSONExtractRaw(attributes, 'referenced_tables') as referenced_tables,
            JSONExtractBool(attributes, 'metadata_only') as metadata_only,
            JSONExtractRaw(attributes, 'referenced_table_metadata') as referenced_table_metadata,
            JSONExtractRaw(attributes, 'connection_metadata') as connection_metadata,
            attributes
        FROM logs
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        placeholders={"where": where},
    )
    rows = _execute_tenant_query_logs(team, query)
    if not rows:
        return None
    return _tenant_query_log_row_to_execution_detail(rows[0])


def summarize_tenant_query_errors(
    *,
    team: Team,
    connection_id: str | None = None,
    tenant_value: object | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    resolved_date_from, resolved_date_to = _tenant_query_observability_window(date_from, date_to)
    resolved_limit = _tenant_query_observability_limit(limit)
    query = parse_select(
        """
        SELECT
            JSONExtractString(attributes, 'connection_id') as connection_id,
            JSONExtractString(attributes, 'tenant_value') as tenant_value,
            JSONExtractRaw(attributes, 'referenced_tables') as referenced_tables,
            JSONExtractString(attributes, 'original_query') as original_query,
            JSONExtractString(attributes, 'error') as error,
            count() as error_count,
            max(timestamp) as last_seen_at,
            avg(JSONExtractFloat(attributes, 'duration_ms')) as average_duration_ms
        FROM logs
        WHERE {where}
        GROUP BY connection_id, tenant_value, referenced_tables, original_query, error
        ORDER BY error_count DESC, last_seen_at DESC
        LIMIT {limit}
        """,
        placeholders={
            "where": _tenant_query_logs_filter(
                date_from=resolved_date_from,
                date_to=resolved_date_to,
                connection_id=connection_id,
                tenant_value=tenant_value,
                success=False,
            ),
            "limit": ast.Constant(value=resolved_limit),
        },
    )
    rows = _execute_tenant_query_logs(team, query)
    return {
        "errors": [
            {
                "connection_id": str(row[0]),
                "tenant_value": str(row[1]),
                "referenced_tables": _parse_log_json_list(row[2]),
                "original_query": str(row[3]),
                "error": str(row[4]),
                "count": int(row[5]),
                "last_seen_at": _serialize_log_timestamp(row[6]),
                "average_duration_ms": float(row[7]) if row[7] is not None else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }


def summarize_tenant_query_usage(
    *,
    team: Team,
    connection_id: str | None = None,
    tenant_value: object | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    resolved_date_from, resolved_date_to = _tenant_query_observability_window(date_from, date_to)
    resolved_limit = _tenant_query_observability_limit(limit)
    query = parse_select(
        """
        SELECT
            JSONExtractString(attributes, 'connection_id') as connection_id,
            JSONExtractString(attributes, 'tenant_value') as tenant_value,
            JSONExtractRaw(attributes, 'referenced_tables') as referenced_tables,
            count() as total_count,
            countIf(JSONExtractBool(attributes, 'success')) as success_count,
            count() - countIf(JSONExtractBool(attributes, 'success')) as error_count,
            sum(JSONExtractInt(attributes, 'row_count')) as total_rows,
            avg(JSONExtractFloat(attributes, 'duration_ms')) as average_duration_ms,
            max(timestamp) as last_seen_at
        FROM logs
        WHERE {where}
        GROUP BY connection_id, tenant_value, referenced_tables
        ORDER BY total_count DESC, last_seen_at DESC
        LIMIT {limit}
        """,
        placeholders={
            "where": _tenant_query_logs_filter(
                date_from=resolved_date_from,
                date_to=resolved_date_to,
                connection_id=connection_id,
                tenant_value=tenant_value,
            ),
            "limit": ast.Constant(value=resolved_limit),
        },
    )
    rows = _execute_tenant_query_logs(team, query)
    return {
        "usage": [
            {
                "connection_id": str(row[0]),
                "tenant_value": str(row[1]),
                "referenced_tables": _parse_log_json_list(row[2]),
                "count": int(row[3]),
                "success_count": int(row[4]),
                "error_count": int(row[5]),
                "total_rows": int(row[6]),
                "average_duration_ms": float(row[7]) if row[7] is not None else None,
                "last_seen_at": _serialize_log_timestamp(row[8]),
            }
            for row in rows
        ],
        "count": len(rows),
    }


def _tenant_query_config_response(
    source: ExternalDataSource,
    config: DataWarehouseTenantQueryConfig | None,
    disabled_tables: list[str] | None = None,
) -> dict[str, object]:
    return {
        "connection_id": str(source.id),
        "enabled": config.enabled if config is not None else False,
        "tenant_column_name": config.tenant_column_name if config is not None else None,
        "tenant_column_type": config.tenant_column_type if config is not None else None,
        "tenant_column_names_by_table": _tenant_column_overrides(config),
        "default_timeout_ms": (config.default_timeout_ms if config is not None else DEFAULT_TENANT_QUERY_TIMEOUT_MS),
        "max_timeout_ms": config.max_timeout_ms if config is not None else DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS,
        "max_result_limit": (config.max_result_limit if config is not None else DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT),
        "enabled_tables": _enabled_table_names(source),
        "disabled_tables": disabled_tables or [],
    }


def get_tenant_query_config(*, team: Team, connection_id: str) -> dict[str, object]:
    source = _get_direct_postgres_source(team, connection_id)
    config = DataWarehouseTenantQueryConfig.objects.filter(
        team_id=team.pk,
        external_data_source_id=source.id,
    ).first()
    return _tenant_query_config_response(source, config)


def configure_tenant_query(
    *,
    team: Team,
    connection_id: str,
    enabled: bool,
    tenant_column_name: str | None,
    tenant_column_names_by_table: Mapping[str, object] | None = None,
    default_timeout_ms: int | None = None,
    max_timeout_ms: int | None = None,
    max_result_limit: int | None = None,
) -> dict[str, object]:
    source = _get_direct_postgres_source(team, connection_id)
    existing_config = DataWarehouseTenantQueryConfig.objects.filter(
        team_id=team.pk,
        external_data_source_id=source.id,
    ).first()

    resolved_tenant_column_name = tenant_column_name or (
        existing_config.tenant_column_name if existing_config is not None else None
    )
    if enabled and not resolved_tenant_column_name:
        raise ExposedHogQLError("Tenant column name is required when enabling tenant queries.")

    if not enabled and existing_config is None and resolved_tenant_column_name is None:
        return _tenant_query_config_response(source, None)

    if resolved_tenant_column_name is None:
        raise ExposedHogQLError("Tenant column name is required.")

    resolved_default_timeout_ms = (
        default_timeout_ms
        if default_timeout_ms is not None
        else (existing_config.default_timeout_ms if existing_config is not None else DEFAULT_TENANT_QUERY_TIMEOUT_MS)
    )
    resolved_max_timeout_ms = (
        max_timeout_ms
        if max_timeout_ms is not None
        else (existing_config.max_timeout_ms if existing_config is not None else DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS)
    )
    if resolved_default_timeout_ms > resolved_max_timeout_ms:
        raise ExposedHogQLError("default_timeout_ms must be less than or equal to max_timeout_ms.")

    all_schemas = _direct_postgres_schemas(source)
    existing_tenant_column_names_by_table = _tenant_column_overrides(existing_config)
    resolved_raw_tenant_column_names_by_table = (
        tenant_column_names_by_table
        if tenant_column_names_by_table is not None
        else existing_tenant_column_names_by_table
    )
    canonical_tenant_column_names_by_table = _canonical_tenant_column_overrides(
        all_schemas,
        resolved_raw_tenant_column_names_by_table,
        resolved_tenant_column_name,
    )

    disabled_tables: list[str] = []
    tenant_column_type = (
        existing_config.tenant_column_type
        if existing_config is not None
        else DataWarehouseTenantQueryConfig.TenantColumnType.STRING
    )
    if enabled:
        schemas_to_configure = [
            schema
            for schema in all_schemas
            if schema.should_sync or _schema_display_name(schema) in canonical_tenant_column_names_by_table
        ]
        if not schemas_to_configure:
            raise ExposedHogQLError("Tenant query service requires at least one enabled table.")

        tenant_column_type = _tenant_column_type_for_effective_columns(
            schemas_to_configure,
            resolved_tenant_column_name,
            canonical_tenant_column_names_by_table,
            tenant_column_type,
        )
        canonical_tenant_column_names_by_table = _validate_tenant_column_overrides(
            all_schemas,
            canonical_tenant_column_names_by_table,
            tenant_column_type,
        )

        override_schema_ids = [
            schema.id
            for schema in all_schemas
            if _schema_display_name(schema) in canonical_tenant_column_names_by_table and not schema.should_sync
        ]
        if override_schema_ids:
            ExternalDataSchema.objects.filter(
                team_id=source.team_id,
                source_id=source.id,
                id__in=override_schema_ids,
            ).update(should_sync=True)
            for schema in all_schemas:
                if schema.id in override_schema_ids:
                    schema.should_sync = True

        enabled_schemas = [schema for schema in all_schemas if schema.should_sync]
        missing_tenant_column_schemas = []
        for schema in enabled_schemas:
            schema_tenant_column_name = canonical_tenant_column_names_by_table.get(
                _schema_display_name(schema),
                resolved_tenant_column_name,
            )
            if _postgres_schema_column(schema, schema_tenant_column_name) is None:
                missing_tenant_column_schemas.append(schema)

        disabled_tables = _disable_schemas_without_tenant_column(source, missing_tenant_column_schemas)
    else:
        canonical_tenant_column_names_by_table = _validate_tenant_column_overrides(
            all_schemas,
            canonical_tenant_column_names_by_table,
            tenant_column_type,
        )

    defaults = {
        "team": team,
        "enabled": enabled,
        "tenant_column_name": resolved_tenant_column_name,
        "tenant_column_type": tenant_column_type,
        "tenant_column_names_by_table": canonical_tenant_column_names_by_table,
        "default_timeout_ms": resolved_default_timeout_ms,
        "max_timeout_ms": resolved_max_timeout_ms,
        "max_result_limit": max_result_limit
        if max_result_limit is not None
        else (
            existing_config.max_result_limit if existing_config is not None else DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT
        ),
    }

    config, _created = DataWarehouseTenantQueryConfig.objects.update_or_create(
        team_id=team.pk,
        external_data_source=source,
        defaults=defaults,
    )
    return _tenant_query_config_response(source, config, disabled_tables=disabled_tables)


def _coerce_tenant_value(config: DataWarehouseTenantQueryConfig, tenant_value: object) -> object:
    if config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER:
        if isinstance(tenant_value, bool):
            raise ExposedHogQLError("Tenant value must be an integer.")
        try:
            return int(str(tenant_value))
        except (TypeError, ValueError) as error:
            raise ExposedHogQLError("Tenant value must be an integer.") from error

    if config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.UUID:
        try:
            return UUID(str(tenant_value))
        except ValueError as error:
            raise ExposedHogQLError("Tenant value must be a UUID.") from error

    if tenant_value is None:
        raise ExposedHogQLError("Tenant value is required.")
    return str(tenant_value)


def _walk_table_nodes(node: TableNode) -> Iterable[DirectPostgresTable]:
    if isinstance(node.table, DirectPostgresTable):
        yield node.table
    for child in node.children.values():
        yield from _walk_table_nodes(child)


def _hide_tenant_field(field: FieldOrTable) -> FieldOrTable:
    return field.model_copy(update={"hidden": True})


class _TenantColumnOutputVisitor(TraversingVisitor):
    def __init__(self, tenant_column_names: set[str]) -> None:
        self.tenant_column_names = tenant_column_names

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        for expr in node.select or []:
            visitor = _TenantColumnFieldReferenceVisitor(self.tenant_column_names)
            visitor.visit(expr)
            if visitor.referenced_tenant_column_name is not None:
                raise ExposedHogQLError(f"Tenant column `{visitor.referenced_tenant_column_name}` cannot be selected.")

        super().visit_select_query(node)


class _TenantColumnFieldReferenceVisitor(TraversingVisitor):
    def __init__(self, tenant_column_names: set[str]) -> None:
        self.tenant_column_names = tenant_column_names
        self.referenced_tenant_column_name: str | None = None

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and str(node.chain[-1]) in self.tenant_column_names:
            self.referenced_tenant_column_name = str(node.chain[-1])
            return

        super().visit_field(node)


def reject_tenant_column_outputs(
    query: ast.SelectQuery | ast.SelectSetQuery,
    tenant_column_names: set[str],
) -> None:
    _TenantColumnOutputVisitor(tenant_column_names).visit(query)


def apply_tenant_query_config(
    database: Database,
    config: DataWarehouseTenantQueryConfig,
    tenant_value: object | None,
) -> None:
    predicate_value = _coerce_tenant_value(config, tenant_value)
    missing_table_names: list[str] = []

    for table in _walk_table_nodes(database.tables):
        tenant_column_name = _tenant_column_name_for_direct_postgres_table(table, config)
        tenant_field = table.fields.get(tenant_column_name)
        if tenant_field is None:
            missing_table_names.append(table.to_printed_hogql())
            continue

        table.fields[tenant_column_name] = _hide_tenant_field(tenant_field)
        table.predicates = [
            *table.predicates,
            ast.CompareOperation(
                left=ast.Field(chain=[tenant_column_name]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=predicate_value),
            ),
        ]

    if missing_table_names:
        table_list = ", ".join(sorted(missing_table_names))
        raise ExposedHogQLError(f"Tenant column is missing from enabled tables: {table_list}.")


def _timeout_ms(config: DataWarehouseTenantQueryConfig, requested_timeout_ms: int | None) -> int:
    timeout_ms = requested_timeout_ms or config.default_timeout_ms or DEFAULT_TENANT_QUERY_TIMEOUT_MS
    max_timeout_ms = config.max_timeout_ms or DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS
    return min(timeout_ms, max_timeout_ms)


def _apply_top_level_tenant_query_limit(
    query: ast.SelectQuery | ast.SelectSetQuery,
    max_result_limit: int,
) -> None:
    if query.limit_percent:
        return

    default_limit = get_default_limit_for_context(LimitContext.TENANT_QUERY)
    if query.limit is None:
        query.limit = ast.Constant(value=min(default_limit, max_result_limit))
        return

    if isinstance(query.limit, ast.Constant) and isinstance(query.limit.value, int):
        query.limit.value = min(query.limit.value, max_result_limit)
        return

    query.limit = ast.Call(
        name="least",
        args=[ast.Constant(value=max_result_limit), query.limit],
    )


def _referenced_direct_postgres_tables(executor: HogQLQueryExecutor) -> list[str]:
    try:
        query_type = executor._get_select_query_type()
    except Exception:
        return []
    if query_type is None:
        return []

    table_names: set[str] = set()
    for table_type in extract_base_table_types(query_type):
        table = table_type.table
        if isinstance(table, DirectPostgresTable):
            table_names.add(table.to_printed_hogql())
    return sorted(table_names)


def _referenced_direct_postgres_table_metadata(executor: HogQLQueryExecutor) -> list[dict[str, object | None]]:
    try:
        query_type = executor._get_select_query_type()
    except Exception:
        return []
    if query_type is None:
        return []

    table_metadata: dict[str, dict[str, object | None]] = {}
    for table_type in extract_base_table_types(query_type):
        table = table_type.table
        if isinstance(table, DirectPostgresTable):
            table_metadata[table.to_printed_hogql()] = {
                "name": table.to_printed_hogql(),
                "postgres_catalog": table.postgres_catalog,
                "postgres_schema": table.postgres_schema,
                "postgres_table_name": table.postgres_table_name,
            }
    return [table_metadata[name] for name in sorted(table_metadata)]


def execute_tenant_query(
    *,
    team: Team,
    user: User | None,
    connection_id: str,
    tenant_value: object | None,
    query: str,
    timeout_ms: int | None = None,
) -> tuple[dict[str, object], int]:
    try:
        config = DataWarehouseTenantQueryConfig.objects.select_related("external_data_source").get(
            team_id=team.pk, external_data_source_id=connection_id
        )
    except DataWarehouseTenantQueryConfig.DoesNotExist as error:
        raise ExposedHogQLError("Tenant query service is not configured for this connection.") from error

    if not config.enabled:
        raise ExposedHogQLError("Tenant query service is disabled for this connection.")
    source = _get_direct_postgres_source(team, str(config.external_data_source_id))

    started_at = perf_counter()
    try:
        metadata_response = execute_tenant_metadata_query(source=source, config=config, query=query)
    except Exception as error:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.info(
            "tenant_query_execution",
            team_id=team.pk,
            connection_id=str(config.external_data_source_id),
            tenant_value=str(tenant_value),
            original_query=query,
            postgres_sql=None,
            referenced_tables=[],
            referenced_table_metadata=[],
            connection_metadata=source.connection_metadata,
            duration_ms=duration_ms,
            row_count=0,
            success=False,
            error=str(error),
            metadata_only=False,
        )
        raise

    if metadata_response is not None:
        result, row_count = metadata_response
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.info(
            "tenant_query_execution",
            team_id=team.pk,
            connection_id=str(config.external_data_source_id),
            tenant_value=str(tenant_value),
            original_query=query,
            postgres_sql=None,
            referenced_tables=[],
            referenced_table_metadata=[],
            connection_metadata=source.connection_metadata,
            duration_ms=duration_ms,
            row_count=row_count,
            success=True,
            error=None,
            metadata_only=True,
        )
        return result, row_count

    try:
        parsed_query = parse_select(query)
        reject_tenant_column_outputs(parsed_query, _tenant_column_output_names(config))
        _apply_top_level_tenant_query_limit(
            parsed_query,
            config.max_result_limit or DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT,
        )
    except Exception as error:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.info(
            "tenant_query_execution",
            team_id=team.pk,
            connection_id=str(config.external_data_source_id),
            tenant_value=str(tenant_value),
            original_query=query,
            postgres_sql=None,
            referenced_tables=[],
            referenced_table_metadata=[],
            connection_metadata=source.connection_metadata,
            duration_ms=duration_ms,
            row_count=0,
            success=False,
            error=str(error),
            metadata_only=False,
        )
        raise

    effective_timeout_ms = _timeout_ms(config, timeout_ms)
    database = Database.create_for(team=team, user=user, connection_id=str(config.external_data_source_id))
    apply_tenant_query_config(database, config, tenant_value)

    context = HogQLContext(
        team_id=team.pk,
        team=team,
        user=user,
        database=database,
        limit_top_select=False,
    )
    executor = HogQLQueryExecutor(
        query=parsed_query,
        team=team,
        query_type="TenantQuery",
        settings=HogQLGlobalSettings(max_execution_time=max((effective_timeout_ms + 999) // 1000, 1)),
        limit_context=LimitContext.TENANT_QUERY,
        context=context,
        connection_id=str(config.external_data_source_id),
        user=user,
    )

    try:
        response = executor.execute()
    except Exception as error:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.info(
            "tenant_query_execution",
            team_id=team.pk,
            connection_id=str(config.external_data_source_id),
            tenant_value=str(tenant_value),
            original_query=query,
            postgres_sql=executor.direct_postgres_sql,
            referenced_tables=_referenced_direct_postgres_tables(executor),
            referenced_table_metadata=_referenced_direct_postgres_table_metadata(executor),
            connection_metadata=source.connection_metadata,
            duration_ms=duration_ms,
            row_count=0,
            success=False,
            error=str(error),
        )
        raise

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    row_count = len(response.results or [])
    postgres_sql = executor.direct_postgres_sql
    logger.info(
        "tenant_query_execution",
        team_id=team.pk,
        connection_id=str(config.external_data_source_id),
        tenant_value=str(tenant_value),
        original_query=query,
        postgres_sql=postgres_sql,
        referenced_tables=_referenced_direct_postgres_tables(executor),
        referenced_table_metadata=_referenced_direct_postgres_table_metadata(executor),
        connection_metadata=source.connection_metadata,
        duration_ms=duration_ms,
        row_count=row_count,
        success=True,
        error=None,
    )

    response_data = response.model_dump(by_alias=True, exclude_none=True)
    response_data["query"] = query
    if postgres_sql is not None:
        response_data["postgres_sql"] = postgres_sql
    return {key: value for key, value in response_data.items() if key in TENANT_QUERY_RESPONSE_FIELDS}, row_count
