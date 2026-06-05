import os
import statistics
from collections.abc import Callable
from time import perf_counter
from typing import Any

import unittest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

# Opt-in: this seeds hundreds/thousands of rows and is meant to be run by hand to compare
# create_hogql_database performance before/after a change, not on every CI run.
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
    # A few realistic named columns first (including *_id columns that exercise the inferred
    # foreign-key path), then filler columns to reach the requested width.
    named = ["id", "name", "created_at", "amount", "is_active", "customer_id", "order_id", "user_id"]
    columns: dict[str, Any] = {}
    for i in range(n_columns):
        name = named[i] if i < len(named) else f"col_{i}"
        is_id = name == "id" or name.endswith("_id")
        hogql_type = "IntegerDatabaseField" if is_id else _HOGQL_TYPES[i % len(_HOGQL_TYPES)]
        columns[name] = {"clickhouse": _HOGQL_TO_CLICKHOUSE[hogql_type], "hogql": hogql_type, "valid": True}
    return columns


def _time(fn: Callable[[], Any], *, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        start = perf_counter()
        fn()
        samples.append((perf_counter() - start) * 1000)
    return min(samples), statistics.median(samples)


@unittest.skipUnless(RUN, "perf benchmark; set RUN_HOGQL_DB_PERF=1 to run")
class TestCreateHogQLDatabasePerf(BaseTest):
    def _seed(self, *, n_tables: int, n_columns: int = 30, n_sources: int = 5, n_joins: int = 10) -> None:
        credentials = [
            DataWarehouseCredential.objects.create(team=self.team, access_key=f"key_{i}", access_secret=f"secret_{i}")
            for i in range(n_sources)
        ]
        sources = [
            ExternalDataSource.objects.create(
                team=self.team,
                source_id=f"src_{i}",
                connection_id=f"conn_{i}",
                source_type=ExternalDataSourceType.POSTGRES,
                status="Completed",
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
                    team=self.team, source_id=t.external_data_source_id, name=t.name, table=t, should_sync=True
                )
                for t in tables
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

    def _resolve_one_table_query(self, *, lazy: bool) -> int:
        """Build the database, resolve a query touching a single table, return #tables built."""
        original = DataWarehouseTable.hogql_definition
        built = {"count": 0}

        def counting(self, *args, **kwargs):
            built["count"] += 1
            return original(self, *args, **kwargs)

        with patch.object(DataWarehouseTable, "hogql_definition", counting):
            database = Database.create_for(team=self.team, lazy_warehouse_tables=lazy)
            table_name = database.get_warehouse_table_names()[0]
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                database=database,
                modifiers=create_default_modifiers_for_team(self.team),
            )
            prepare_and_print_ast(parse_select(f"SELECT * FROM {table_name} LIMIT 100"), context, dialect="clickhouse")
        return built["count"]

    @parameterized.expand([(50,), (250,), (1000,)])
    def test_benchmark(self, n_tables: int) -> None:
        self._seed(n_tables=n_tables)

        print(f"\n=== create_hogql_database perf: {n_tables} warehouse tables ===")  # noqa: T201
        for lazy in (False, True):
            label = "lazy " if lazy else "eager"
            build_min, build_median = _time(
                lambda lazy=lazy: Database.create_for(team=self.team, lazy_warehouse_tables=lazy), iterations=5
            )
            resolve_min, resolve_median = _time(
                lambda lazy=lazy: self._resolve_one_table_query(lazy=lazy), iterations=5
            )
            tables_built = self._resolve_one_table_query(lazy=lazy)
            print(f"  [{label}] create_for only            min={build_min:8.1f}ms  median={build_median:8.1f}ms")  # noqa: T201
            print(  # noqa: T201
                f"  [{label}] create_for + resolve 1 tbl min={resolve_min:8.1f}ms  median={resolve_median:8.1f}ms"
            )
            print(f"  [{label}] tables built to resolve 1  {tables_built} / {n_tables}")  # noqa: T201
