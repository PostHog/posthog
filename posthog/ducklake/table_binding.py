from __future__ import annotations

from typing import Any

from posthog.ducklake.common import (
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    duckgres_data_modeling_schema,
)


def bind_tables_to_ducklake(database: Any, team_id: int) -> None:
    """Bind a built HogQL database's tables to their duckgres-materialized counterparts.

    On the warehouse HogQL database, both materialized data-modeling models and
    imported source tables resolve to the ClickHouse S3 table function (``s3(...)``),
    which DuckDB/duckgres cannot execute. The duckgres materialization / copy
    workflows write these into DuckLake schemas, so rebind each table node to a
    ``DirectPostgresTable`` that prints as the schema-qualified DuckLake name.

    Mutates ``database`` in place. Scoped to the DuckLake compile path only — the
    ClickHouse path never calls this, so its table resolution is unchanged.
    """
    _bind_materialized_models(database, team_id)
    _bind_source_tables(database, team_id)


def _bind_materialized_models(database: Any, team_id: int) -> None:
    """Bind materialized data-modeling models to their DuckLake schema (``shadow_<team_id>_models``)."""
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    schema_name = duckgres_data_modeling_schema(team_id)
    materialized = DataWarehouseSavedQuery.objects.filter(
        team_id=team_id, is_materialized=True, table__isnull=False
    ).exclude(deleted=True)
    for saved_query in materialized:
        try:
            node = database.get_table_node(saved_query.name.split("."))
        except Exception:
            continue
        existing = node.table
        if existing is None:
            continue
        node.table = DirectPostgresTable(
            name=saved_query.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=saved_query.normalized_name,
            fields=existing.fields,
        )


def _bind_source_tables(database: Any, team_id: int) -> None:
    """Bind imported source tables to their DuckLake-copied counterparts.

    Each queryable, S3-backed warehouse table that has a linked ``ExternalDataSchema`` was
    copied into the team's data-imports schema by the copy workflow. Model backing tables
    have no schema, so they are naturally skipped; direct-query tables already render
    schema-qualified and are not S3-backed, so they are skipped too. The binding is blind —
    if a table hasn't been synced yet, duckgres errors at query time, which is intended.
    """
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable

    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    schema_name = duckgres_data_imports_schema(team_id)
    tables = (
        DataWarehouseTable.objects.queryable()
        .filter(team_id=team_id, external_data_source__isnull=False)
        .exclude(external_data_source__access_method=ExternalDataSource.AccessMethod.DIRECT)
    )
    for table in tables:
        external_schema = table.externaldataschema_set.first()
        if external_schema is None:
            continue
        try:
            node = database.get_table_node(table.name_chain)
        except Exception:
            continue
        existing = node.table
        if existing is None:
            continue
        node.table = DirectPostgresTable(
            name=table.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=duckgres_data_imports_table_name(external_schema),
            fields=existing.fields,
        )
