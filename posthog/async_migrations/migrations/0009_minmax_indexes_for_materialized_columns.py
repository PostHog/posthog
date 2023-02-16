from functools import cached_property, partial
from typing import List

import structlog
from clickhouse_driver.errors import ServerException
from django.conf import settings

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.clickhouse.materialized_columns import get_materialized_columns
from posthog.client import sync_execute
from posthog.models.property.property import TableWithProperties

logger = structlog.get_logger(__name__)

TABLES_TO_INDEX: List[TableWithProperties] = ["events", "person", "groups"]


class Migration(AsyncMigrationDefinition):
    description = "Create minmax indexes for materialized columns to speed up queries"

    depends_on = "0008_speed_up_kafka_timestamp_filters"
    posthog_min_version = "1.43.0"
    posthog_max_version = "1.49.99"

    def is_required(self):
        return settings.EE_AVAILABLE and any(self.has_missing_index(table) for table in TABLES_TO_INDEX)

    def has_missing_index(self, table: TableWithProperties) -> bool:
        table_to_check = "sharded_events" if table == "events" else table
        indexes = set(
            row[0]
            for row in sync_execute(
                "SELECT name FROM system.data_skipping_indices WHERE table = %(table)s", {"table": table_to_check}
            )
        )
        return any(f"minmax_{column_name}" not in indexes for column_name in get_materialized_columns(table).values())

    @cached_property
    def operations(self):
        operations = []
        for table in TABLES_TO_INDEX:
            for column_name in get_materialized_columns(table).values():
                operations.append(
                    AsyncMigrationOperation(fn=partial(self.attempt_add_materialized_column_index, table, column_name))
                )

        return operations

    def attempt_add_materialized_column_index(self, table: TableWithProperties, column_name: str, query_id: str):
        from ee.clickhouse.materialized_columns.columns import add_minmax_index

        execute_on_cluster = f"ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'" if table == "events" else ""
        updated_table = "sharded_events" if table == "events" else table

        try:
            index_name = add_minmax_index(table, column_name)
            sync_execute(
                f"""
                ALTER TABLE {updated_table}
                {execute_on_cluster}
                MATERIALIZE INDEX {index_name}
                """,
                {"mutations_sync": 2},
            )
        except ServerException as err:
            # We ignore indexes that already exist (due to being added before this migration runs)
            if "index with this name already exists" not in str(err):
                raise err
