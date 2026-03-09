from typing import TypeVar

from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import FunctionCallTable, TableNode
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.s3_table import S3Table

from products.data_warehouse.backend.models import ExternalDataSource

TTable = TypeVar("TTable")


def connection_source_identifiers(source: ExternalDataSource | None) -> set[str] | None:
    if source is None:
        return None

    return {str(source.id)}


def filter_schema_tables_for_connection(tables: dict[str, TTable], source_ids: set[str] | None) -> dict[str, TTable]:
    filtered_tables: dict[str, TTable]
    if not source_ids:
        filtered_tables = {
            name: table
            for name, table in tables.items()
            if not (
                getattr(table, "type", None) == "data_warehouse"
                and getattr(getattr(table, "source", None), "access_method", None)
                == ExternalDataSource.AccessMethod.DIRECT
            )
        }
        _remove_inaccessible_lazy_joins(filtered_tables)
        return filtered_tables

    def is_queriable(table: TTable) -> bool:
        schema = getattr(table, "schema_", None) or getattr(table, "schema", None)
        if schema is None:
            return True
        if isinstance(schema, dict):
            return bool(schema.get("should_sync", False))
        return bool(getattr(schema, "should_sync", False))

    filtered_tables = {
        name: table
        for name, table in tables.items()
        if getattr(table, "type", None) == "data_warehouse"
        and str(getattr(getattr(table, "source", None), "id", "")) in source_ids
        and is_queriable(table)
    }
    _remove_inaccessible_lazy_joins(filtered_tables)
    return filtered_tables


def _remove_inaccessible_lazy_joins(tables: dict[str, TTable]) -> None:
    allowed_table_names = set(tables.keys())

    for table in tables.values():
        fields = getattr(table, "fields", None)
        if not isinstance(fields, dict):
            continue

        for field_name, field in list(fields.items()):
            if getattr(field, "type", None) != "lazy_table":
                continue

            if getattr(field, "table", None) not in allowed_table_names:
                del fields[field_name]


def _is_helper_function_table(table: object) -> bool:
    return isinstance(table, FunctionCallTable) and not isinstance(table, (DirectPostgresTable, PostgresTable, S3Table))


def prune_database_for_connection(database: Database, allowed_table_names: set[str]) -> None:
    def prune_node(node: TableNode, chain: list[str]) -> bool:
        full_name = ".".join(chain)
        keep_table = node.table is not None and (
            full_name in allowed_table_names or (len(chain) > 0 and _is_helper_function_table(node.table))
        )

        pruned_children: dict[str, TableNode] = {}
        for child_name, child in node.children.items():
            if prune_node(child, [*chain, child_name]):
                pruned_children[child_name] = child
        node.children = pruned_children

        return node.name == "root" or keep_table or len(node.children) > 0

    prune_node(database.tables, [])
    database._warehouse_table_names = [name for name in database._warehouse_table_names if name in allowed_table_names]
    database._warehouse_self_managed_table_names = [
        name for name in database._warehouse_self_managed_table_names if name in allowed_table_names
    ]
    database._view_table_names = [name for name in database._view_table_names if name in allowed_table_names]
