from __future__ import annotations

from collections.abc import Iterable
from time import perf_counter
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import FieldOrTable, TableNode
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor
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


def _get_direct_postgres_source(team: Team, connection_id: str) -> ExternalDataSource:
    try:
        source = ExternalDataSource.objects.exclude(deleted=True).get(team_id=team.pk, id=connection_id)
    except ExternalDataSource.DoesNotExist as error:
        raise ExposedHogQLError("Direct Postgres connection not found.") from error

    if not source.is_direct_postgres:
        raise ExposedHogQLError("Tenant query service requires a direct Postgres connection.")

    return source


def _enabled_direct_postgres_schemas(source: ExternalDataSource) -> list[ExternalDataSchema]:
    return list(
        ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id)
        .exclude(deleted=True)
        .filter(should_sync=True, table_id__isnull=False)
        .select_related("table")
    )


def _schema_display_name(schema: ExternalDataSchema) -> str:
    if schema.table is not None:
        return schema.table.name
    return schema.name


def _enabled_table_names(source: ExternalDataSource) -> list[str]:
    return sorted(_schema_display_name(schema) for schema in _enabled_direct_postgres_schemas(source))


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


def _schema_metadata_value(schema: ExternalDataSchema, key: str) -> str | None:
    metadata = schema.schema_metadata
    if metadata is None:
        return None
    value = metadata.get(key)
    return value if isinstance(value, str) else None


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


def infer_tenant_column_type(source: ExternalDataSource, tenant_column_name: str) -> str:
    if not source.is_direct_postgres:
        raise ExposedHogQLError("Tenant query service requires a direct Postgres connection.")

    schemas = _enabled_direct_postgres_schemas(source)
    if not schemas:
        raise ExposedHogQLError("Tenant query service requires at least one enabled table.")

    inferred_types: set[str] = set()
    missing_table_names: list[str] = []

    for schema in schemas:
        column = next(
            (column for column in _postgres_schema_columns(schema) if column.get("name") == tenant_column_name),
            None,
        )
        if column is None:
            missing_table_names.append(_schema_display_name(schema))
            continue

        postgres_type = column.get("data_type")
        if not isinstance(postgres_type, str):
            raise ExposedHogQLError(f"Unable to infer tenant column type for table `{_schema_display_name(schema)}`.")
        inferred_types.add(_tenant_column_type_from_postgres(postgres_type))

    if missing_table_names:
        table_list = ", ".join(sorted(missing_table_names))
        raise ExposedHogQLError(f"Tenant column `{tenant_column_name}` is missing from enabled tables: {table_list}.")

    if len(inferred_types) != 1:
        type_list = ", ".join(sorted(inferred_types))
        raise ExposedHogQLError(f"Tenant column `{tenant_column_name}` has inconsistent types: {type_list}.")

    return next(iter(inferred_types))


def _tenant_metadata_table_rows(source: ExternalDataSource) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for schema in _enabled_direct_postgres_schemas(source):
        rows.append(
            {
                "name": _schema_display_name(schema),
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
    for schema in _enabled_direct_postgres_schemas(source):
        table_name = _schema_display_name(schema)
        for column in _postgres_schema_columns(schema):
            column_name = column.get("name")
            postgres_type = column.get("data_type")
            if not isinstance(column_name, str) or not isinstance(postgres_type, str):
                continue
            if column_name == config.tenant_column_name:
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
        if isinstance(expr.left, ast.Field) and isinstance(expr.right, ast.Constant) and len(expr.left.chain) == 1:
            return row.get(str(expr.left.chain[0])) == expr.right.value
        if isinstance(expr.right, ast.Field) and isinstance(expr.left, ast.Constant) and len(expr.right.chain) == 1:
            return row.get(str(expr.right.chain[0])) == expr.left.value
    raise ExposedHogQLError("Tenant metadata queries only support equality filters joined with AND.")


def _selected_metadata_columns(select_query: ast.SelectQuery, table_name: str) -> list[tuple[str, str]]:
    available_columns = TENANT_METADATA_COLUMNS[table_name]
    if len(select_query.select) == 1:
        expr = select_query.select[0]
        if isinstance(expr, ast.Field) and expr.chain in (["*"], [table_name, "*"]):
            return [(column, column) for column in available_columns]

    selected_columns: list[tuple[str, str]] = []
    for expr in select_query.select:
        alias: str | None = None
        if isinstance(expr, ast.Alias):
            alias = expr.alias
            expr = expr.expr
        if not isinstance(expr, ast.Field) or len(expr.chain) != 1:
            raise ExposedHogQLError("Tenant metadata queries only support selecting metadata columns.")

        column_name = str(expr.chain[0])
        if column_name not in available_columns:
            raise ExposedHogQLError(f"Unknown tenant metadata column `{column_name}`.")
        selected_columns.append((column_name, alias or column_name))

    return selected_columns


def execute_tenant_metadata_query(
    *,
    source: ExternalDataSource,
    config: DataWarehouseTenantQueryConfig,
    query: str,
) -> tuple[dict[str, object], int] | None:
    select_query = parse_select(query)
    if not isinstance(select_query, ast.SelectQuery):
        return None

    table_name = _metadata_table_name(select_query)
    if table_name is None:
        return None

    if table_name == "tables":
        rows = _tenant_metadata_table_rows(source)
    else:
        rows = _tenant_metadata_field_rows(source, config)

    rows = [row for row in rows if _metadata_filter_matches(row, select_query.where)]
    selected_columns = _selected_metadata_columns(select_query, table_name)
    offset = _metadata_offset(select_query)
    limit = _metadata_limit(select_query, config.max_result_limit or DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT)
    page = rows[offset : offset + limit]

    columns = [alias for _column, alias in selected_columns]
    results = [[row[column] for column, _alias in selected_columns] for row in page]
    return (
        {
            "query": query,
            "hogql": query,
            "columns": columns,
            "types": [[alias, TENANT_METADATA_COLUMN_TYPES[column]] for column, alias in selected_columns],
            "results": results,
            "timings": [],
            "limit": limit,
            "offset": offset,
            "hasMore": offset + limit < len(rows),
        },
        len(results),
    )


def _tenant_query_config_response(
    source: ExternalDataSource, config: DataWarehouseTenantQueryConfig | None
) -> dict[str, object]:
    return {
        "connection_id": str(source.id),
        "enabled": config.enabled if config is not None else False,
        "tenant_column_name": config.tenant_column_name if config is not None else None,
        "tenant_column_type": config.tenant_column_type if config is not None else None,
        "default_timeout_ms": (config.default_timeout_ms if config is not None else DEFAULT_TENANT_QUERY_TIMEOUT_MS),
        "max_timeout_ms": config.max_timeout_ms if config is not None else DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS,
        "max_result_limit": (config.max_result_limit if config is not None else DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT),
        "enabled_tables": _enabled_table_names(source),
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

    tenant_column_type = infer_tenant_column_type(source, resolved_tenant_column_name)
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

    defaults = {
        "team": team,
        "enabled": enabled,
        "tenant_column_name": resolved_tenant_column_name,
        "tenant_column_type": tenant_column_type,
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
    return _tenant_query_config_response(source, config)


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
    def __init__(self, tenant_column_name: str) -> None:
        self.tenant_column_name = tenant_column_name

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        for expr in node.select or []:
            visitor = _TenantColumnFieldReferenceVisitor(self.tenant_column_name)
            visitor.visit(expr)
            if visitor.references_tenant_column:
                raise ExposedHogQLError(f"Tenant column `{self.tenant_column_name}` cannot be selected.")

        super().visit_select_query(node)


class _TenantColumnFieldReferenceVisitor(TraversingVisitor):
    def __init__(self, tenant_column_name: str) -> None:
        self.tenant_column_name = tenant_column_name
        self.references_tenant_column = False

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and str(node.chain[-1]) == self.tenant_column_name:
            self.references_tenant_column = True
            return

        super().visit_field(node)


def reject_tenant_column_outputs(
    query: ast.SelectQuery | ast.SelectSetQuery,
    tenant_column_name: str,
) -> None:
    _TenantColumnOutputVisitor(tenant_column_name).visit(query)


def apply_tenant_query_config(
    database: Database,
    config: DataWarehouseTenantQueryConfig,
    tenant_value: object | None,
) -> None:
    predicate_value = _coerce_tenant_value(config, tenant_value)
    missing_table_names: list[str] = []

    for table in _walk_table_nodes(database.tables):
        tenant_field = table.fields.get(config.tenant_column_name)
        if tenant_field is None:
            missing_table_names.append(table.to_printed_hogql())
            continue

        table.fields[config.tenant_column_name] = _hide_tenant_field(tenant_field)
        table.predicates = [
            *table.predicates,
            ast.CompareOperation(
                left=ast.Field(chain=[config.tenant_column_name]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=predicate_value),
            ),
        ]

    if missing_table_names:
        table_list = ", ".join(sorted(missing_table_names))
        raise ExposedHogQLError(
            f"Tenant column `{config.tenant_column_name}` is missing from enabled tables: {table_list}."
        )


def _timeout_ms(config: DataWarehouseTenantQueryConfig, requested_timeout_ms: int | None) -> int:
    timeout_ms = requested_timeout_ms or config.default_timeout_ms or DEFAULT_TENANT_QUERY_TIMEOUT_MS
    max_timeout_ms = config.max_timeout_ms or DEFAULT_TENANT_QUERY_MAX_TIMEOUT_MS
    return min(timeout_ms, max_timeout_ms)


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
        reject_tenant_column_outputs(parsed_query, config.tenant_column_name)
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
        max_limit_override=config.max_result_limit or DEFAULT_TENANT_QUERY_MAX_RESULT_LIMIT,
    )
    executor = HogQLQueryExecutor(
        query=query,
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
    if postgres_sql is not None:
        response_data["postgres_sql"] = postgres_sql
    return {key: value for key, value in response_data.items() if key in TENANT_QUERY_RESPONSE_FIELDS}, row_count
