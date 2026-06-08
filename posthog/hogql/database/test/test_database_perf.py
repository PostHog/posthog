import os
import statistics
from collections.abc import Callable
from time import perf_counter
from typing import Any, cast
from uuid import UUID

import unittest
from posthog.test.base import BaseTest

from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

# Opt-in: this seeds hundreds of rows and is meant to be run by hand to compare create_hogql_database
# performance before/after a change, not on every CI run. To A/B against master, run it on this branch,
# then check out master's database.py over the worktree and run it again (this file only uses the public
# Database.create_for API, which exists on both):
#   RUN_HOGQL_DB_PERF=1 hogli test posthog/hogql/database/test/test_database_perf.py -s
RUN = os.environ.get("RUN_HOGQL_DB_PERF") == "1"

_HOGQL_TO_CLICKHOUSE = {
    "StringDatabaseField": "String",
    "IntegerDatabaseField": "Int64",
    "DateTimeDatabaseField": "DateTime64(3, 'UTC')",
    "FloatDatabaseField": "Float64",
    "BooleanDatabaseField": "Bool",
}
_HOGQL_TYPES = list(_HOGQL_TO_CLICKHOUSE.keys())


def _make_columns(n_columns: int) -> dict[str, Any]:
    # Realistic named columns first (including *_id columns that exercise the inferred foreign-key
    # path), then filler columns to reach the requested width.
    named = ["id", "name", "created_at", "amount", "is_active", "customer_id", "order_id", "user_id"]
    columns: dict[str, Any] = {}
    for i in range(n_columns):
        name = named[i] if i < len(named) else f"col_{i}"
        is_id = name == "id" or name.endswith("_id")
        hogql_type = "IntegerDatabaseField" if is_id else _HOGQL_TYPES[i % len(_HOGQL_TYPES)]
        columns[name] = {"clickhouse": _HOGQL_TO_CLICKHOUSE[hogql_type], "hogql": hogql_type, "valid": True}
    return columns


def _stats(fn: Callable[[], Any], *, iterations: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(iterations):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000)
    return {
        "min": min(samples),
        "median": statistics.median(samples),
        "mean": statistics.mean(samples),
        "max": max(samples),
    }


@unittest.skipUnless(RUN, "perf benchmark; set RUN_HOGQL_DB_PERF=1 to run")
class TestCreateHogQLDatabasePerf(BaseTest):
    def _seed(self, *, n_tables: int, n_columns: int = 40, n_sources: int = 6, n_views: int = 60, n_joins: int = 20):
        credentials = [
            DataWarehouseCredential.objects.create(team=self.team, access_key=f"key_{i}", access_secret=f"secret_{i}")
            for i in range(n_sources)
        ]
        sources = [
            ExternalDataSource.objects.create(
                team=self.team,
                source_id=f"src_{i}",
                connection_id=f"conn_{i}",
                source_type=ExternalDataSourceType.STRIPE if i % 2 == 0 else ExternalDataSourceType.POSTGRES,
                status="Completed",
                prefix=f"p{i}_",
                access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            )
            for i in range(n_sources)
        ]
        columns = _make_columns(n_columns)
        DataWarehouseTable.objects.bulk_create(
            [
                DataWarehouseTable(
                    team=self.team,
                    name=f"table_{i}",
                    format=DataWarehouseTable.TableFormat.Parquet,
                    url_pattern=f"s3://bucket/table_{i}/*.parquet",
                    credential=credentials[i % n_sources],
                    external_data_source=sources[i % n_sources],
                    columns=columns,
                )
                for i in range(n_tables)
            ]
        )
        tables = list(DataWarehouseTable.objects.filter(team=self.team).order_by("id"))
        ExternalDataSchema.objects.bulk_create(
            [
                ExternalDataSchema(
                    team=self.team,
                    source_id=cast(UUID, t.external_data_source_id),
                    name=t.name,
                    table=t,
                    should_sync=True,
                )
                for t in tables
            ]
        )
        # Saved-query "views" referencing the warehouse tables (the data_warehouse_saved_query path).
        DataWarehouseSavedQuery.objects.bulk_create(
            [
                DataWarehouseSavedQuery(
                    team=self.team,
                    name=f"view_{i}",
                    query={"query": f"SELECT id, amount FROM table_{i}"},
                    columns={
                        "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True},
                        "amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField", "valid": True},
                    },
                    status=DataWarehouseSavedQuery.Status.COMPLETED,
                )
                for i in range(min(n_views, n_tables))
            ]
        )
        DataWarehouseJoin.objects.bulk_create(
            [
                DataWarehouseJoin(
                    team=self.team,
                    source_table_name=tables[i].name,
                    source_table_key="id",
                    joining_table_name=tables[i + 1].name,
                    joining_table_key="id",
                    field_name=f"joined_{i}",
                )
                for i in range(min(n_joins, n_tables - 1))
            ]
        )

    def test_benchmark(self) -> None:
        n_tables = int(os.environ.get("HOGQL_DB_PERF_TABLES", "300"))
        self._seed(n_tables=n_tables)
        iterations, warmup = 10, 3

        print(f"\n=== create_hogql_database perf: {n_tables} warehouse tables, 60 views, 20 joins ===")  # noqa: T201

        total = _stats(lambda: Database.create_for(team=self.team), iterations=iterations, warmup=warmup)
        print(  # noqa: T201
            f"  create_for (total)   min={total['min']:8.1f}  median={total['median']:8.1f}  "
            f"mean={total['mean']:8.1f}  max={total['max']:8.1f}  ms"
        )

        # Branch-only: time the fetch (I/O) and build (pure) phases separately to show the split.
        if hasattr(Database, "_fetch_sources") and hasattr(Database, "_build_from_sources"):
            modifiers = create_default_modifiers_for_team(self.team)
            fetch = _stats(
                lambda: Database._fetch_sources(team=self.team, modifiers=modifiers),
                iterations=iterations,
                warmup=warmup,
            )
            sources = Database._fetch_sources(team=self.team, modifiers=modifiers)
            build = _stats(lambda: Database._build_from_sources(sources), iterations=iterations, warmup=warmup)
            print(  # noqa: T201
                f"  _fetch_sources (I/O) min={fetch['min']:8.1f}  median={fetch['median']:8.1f}  "
                f"mean={fetch['mean']:8.1f}  ms"
            )
            print(  # noqa: T201
                f"  _build_from_sources  min={build['min']:8.1f}  median={build['median']:8.1f}  "
                f"mean={build['mean']:8.1f}  ms"
            )
