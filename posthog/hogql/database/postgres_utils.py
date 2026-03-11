import dataclasses
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import LazyJoin, LazyJoinToAdd, Table
from posthog.hogql.database.utils import get_join_field_chain
from posthog.hogql.errors import ResolutionError

from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


class DatabaseTableLookup(Protocol):
    def has_table(self, table_name: str | list[str]) -> bool: ...

    def get_table(self, table_name: str | list[str]) -> Table: ...


@dataclasses.dataclass(frozen=True)
class WarehouseForeignKey:
    column: str
    target_table: str
    target_column: str


def add_postgres_foreign_key_lazy_joins(
    hogql_table: Table,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
    schemas: Sequence[ExternalDataSchema],
) -> None:
    foreign_keys = _get_foreign_keys_from_schemas(schemas)

    for foreign_key in foreign_keys:
        _add_foreign_key_lazy_join(
            hogql_table=hogql_table,
            warehouse_table=warehouse_table,
            database=database,
            column=foreign_key.column,
            target_table=foreign_key.target_table,
            target_column=foreign_key.target_column,
        )

    if foreign_keys:
        return

    # Fallback inference when explicit FK metadata is unavailable.
    # This keeps direct Postgres ergonomics high for common *_id columns.
    if not isinstance(hogql_table.name, str):
        return

    namespace = hogql_table.name.split(".")[:-1]
    columns = warehouse_table.columns or {}

    for column_name in columns.keys():
        if not column_name.endswith("_id") or len(column_name) <= 3:
            continue

        field_name = column_name[:-3]
        if hogql_table.fields.get(field_name):
            continue

        target_table_name = _find_inferred_target_table_name(
            base_name=field_name,
            namespace=namespace,
            hogql_table=hogql_table,
            warehouse_table=warehouse_table,
            database=database,
        )
        if target_table_name is None:
            continue

        _add_foreign_key_lazy_join(
            hogql_table=hogql_table,
            warehouse_table=warehouse_table,
            database=database,
            column=column_name,
            target_table=target_table_name,
            target_column="id",
        )


def _get_foreign_keys_from_schemas(schemas: Sequence[ExternalDataSchema]) -> list[WarehouseForeignKey]:
    schema_with_foreign_keys = next((schema for schema in schemas if _get_foreign_keys(schema)), None)
    return _get_foreign_keys(schema_with_foreign_keys) if schema_with_foreign_keys is not None else []


def _get_foreign_keys(schema: ExternalDataSchema | None) -> list[WarehouseForeignKey]:
    if schema is None:
        return []

    raw_foreign_keys: Any = schema.foreign_keys
    if raw_foreign_keys is None:
        metadata = schema.sync_type_config.get("schema_metadata") if schema.sync_type_config else None
        if isinstance(metadata, dict):
            raw_foreign_keys = metadata.get("foreign_keys")

    if not isinstance(raw_foreign_keys, list):
        return []

    foreign_keys: list[WarehouseForeignKey] = []
    for foreign_key in raw_foreign_keys:
        if not isinstance(foreign_key, dict):
            continue

        column = foreign_key.get("column")
        target_table = foreign_key.get("target_table")
        target_column = foreign_key.get("target_column")
        if not (isinstance(column, str) and isinstance(target_table, str) and isinstance(target_column, str)):
            continue

        foreign_keys.append(WarehouseForeignKey(column=column, target_table=target_table, target_column=target_column))

    return foreign_keys


def _add_foreign_key_lazy_join(
    *,
    hogql_table: Table,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
    column: str,
    target_table: str,
    target_column: str,
) -> None:
    if not column or not target_table or not target_column:
        return

    try:
        from_field = get_join_field_chain(column)
        to_field = get_join_field_chain(target_column)
    except Exception as error:
        capture_exception(error)
        return

    if from_field is None or to_field is None:
        return

    field_name = column[:-3] if column.endswith("_id") and len(column) > 3 else column
    if hogql_table.fields.get(field_name):
        return

    resolved_target = _resolve_target_table(
        target_table=target_table,
        source_table_name=hogql_table.name if isinstance(hogql_table.name, str) else None,
        database=database,
    )
    if resolved_target is None:
        return

    join_table, target_hogql_table = resolved_target
    if not _is_same_external_scope(hogql_table, target_hogql_table, warehouse_table):
        return

    hogql_table.fields[field_name] = LazyJoin(
        from_field=from_field,
        to_field=to_field,
        join_table=join_table,
        join_function=_foreign_key_join_function(from_field, to_field),
    )

    target_table_name = target_hogql_table.name if isinstance(target_hogql_table.name, str) else None
    source_table_name = hogql_table.name if isinstance(hogql_table.name, str) else None
    if target_table_name is None or source_table_name is None:
        return

    reverse_field_name = _reverse_foreign_key_field_name(source_table_name, target_table_name)
    if target_hogql_table.fields.get(reverse_field_name) is not None:
        return

    target_hogql_table.fields[reverse_field_name] = LazyJoin(
        from_field=to_field,
        to_field=from_field,
        join_table=hogql_table,
        join_function=_foreign_key_join_function(to_field, from_field),
    )


def _resolve_target_table(
    *,
    target_table: str,
    source_table_name: str | None,
    database: DatabaseTableLookup,
) -> tuple[Table | str, Table] | None:
    join_table: Table | str = target_table
    if (
        source_table_name is not None
        and isinstance(join_table, str)
        and "." in source_table_name
        and "." not in join_table
    ):
        join_table = ".".join([*source_table_name.split(".")[:-1], join_table])

    if isinstance(join_table, str):
        if not database.has_table(join_table):
            return None

        return join_table, database.get_table(join_table)

    return join_table, join_table


def _is_same_external_scope(
    source_hogql_table: Table,
    target_hogql_table: Table,
    warehouse_table: DataWarehouseTable,
) -> bool:
    source_table_name = source_hogql_table.name if isinstance(source_hogql_table.name, str) else None
    target_table_name = target_hogql_table.name if isinstance(target_hogql_table.name, str) else None
    if source_table_name is None or target_table_name is None:
        return False

    source = warehouse_table.external_data_source
    if source is not None and source.access_method == ExternalDataSource.AccessMethod.DIRECT:
        return isinstance(
            target_hogql_table, DirectPostgresTable
        ) and target_hogql_table.external_data_source_id == str(source.id)

    if "." not in source_table_name or "." not in target_table_name:
        return False

    return source_table_name.rsplit(".", 1)[0] == target_table_name.rsplit(".", 1)[0]


def _foreign_key_join_function(
    from_field: list[str | int], to_field: list[str | int]
) -> Callable[[LazyJoinToAdd, HogQLContext, ast.SelectQuery], ast.JoinExpr]:
    def _join_function(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery):
        join_table = join_to_add.lazy_join.resolve_table(context)

        if isinstance(join_table.name, str):
            join_table_chain = cast(list[str | int], join_table.name.split("."))
        else:
            join_table_chain = [join_to_add.to_table]

        if not join_to_add.fields_accessed:
            raise ResolutionError(f"No fields requested from {join_to_add.to_table}")

        left = ast.Field(chain=[join_to_add.from_table, *from_field])
        right = ast.Field(chain=[join_to_add.to_table, *to_field])

        return ast.JoinExpr(
            table=ast.SelectQuery(
                select=[
                    ast.Alias(alias=alias, expr=ast.Field(chain=chain))
                    for alias, chain in join_to_add.fields_accessed.items()
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=join_table_chain)),
            ),
            join_type="LEFT JOIN",
            alias=join_to_add.to_table,
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=left, right=right),
                constraint_type="ON",
            ),
        )

    return _join_function


def _reverse_foreign_key_field_name(from_table: str, target_table: str) -> str:
    from_base = from_table.split(".")[-1]
    target_base = target_table.split(".")[-1]

    if from_base.startswith(target_base):
        reverse_name = from_base[len(target_base) :].lstrip("_") or from_base
    else:
        reverse_name = from_base

    if not reverse_name.endswith("s"):
        reverse_name = f"{reverse_name}s"

    return reverse_name


def _find_inferred_target_table_name(
    *,
    base_name: str,
    namespace: list[str],
    hogql_table: Table,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
) -> str | None:
    for candidate in _candidate_target_tables(base_name=base_name, namespace=namespace):
        if not database.has_table(candidate):
            continue

        target_hogql_table = database.get_table(candidate)
        if _is_same_external_scope(hogql_table, target_hogql_table, warehouse_table):
            return candidate

    return None


def _candidate_target_tables(*, base_name: str, namespace: list[str]) -> list[str]:
    local_candidates = [base_name, f"{base_name}s", f"posthog_{base_name}"]
    scoped_candidates = [".".join([*namespace, candidate]) for candidate in local_candidates] if namespace else []
    return scoped_candidates or local_candidates
