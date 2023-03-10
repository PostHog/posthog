from functools import cached_property, partial
from typing import List, Set

import structlog
from django.conf import settings

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.clickhouse.materialized_columns import ColumnName, get_materialized_columns
from posthog.client import sync_execute
from posthog.models.property.property import TableWithProperties
from posthog.utils import chunked_iterable

logger = structlog.get_logger(__name__)

TABLES_TO_INDEX: List[TableWithProperties] = ["events", "person", "groups"]


class Migration(AsyncMigrationDefinition):
    description = "Create minmax indexes for materialized columns to speed up queries"

    depends_on = "0009_minmax_indexes_for_materialized_columns"
    posthog_min_version = "1.43.0"
    posthog_max_version = "1.49.99"

    def is_required(self):
        return settings.EE_AVAILABLE and any(self.has_missing_index(table) for table in TABLES_TO_INDEX)

    def get_indexed_columns(self, table: TableWithProperties) -> Set[ColumnName]:
        table_to_check = "sharded_events" if table == "events" else table
        index_expressions = sync_execute(
            """
            SELECT expr
            FROM system.data_skipping_indices
            WHERE table = %(table)s
              AND name LIKE %(pattern)s
            """,
            {"table": table_to_check, "pattern": "minmax_%"},
        )

        indexed_columns: Set[ColumnName] = set()
        for (expression,) in index_expressions:
            indexed_columns |= set(expr.strip("`") for expr in expression.split(", "))

        return indexed_columns

    def has_missing_index(self, table: TableWithProperties) -> bool:
        already_indexed = self.get_indexed_columns(table)
        return any(column_name not in already_indexed for column_name in get_materialized_columns(table).values())

    @cached_property
    def operations(self):
        operations = []
        for table in TABLES_TO_INDEX:
            for column_names in chunked_iterable(
                get_materialized_columns(table).values(), settings.MATERIALIZE_COLUMNS_MAX_AT_ONCE
            ):
                operations.append(
                    AsyncMigrationOperation(fn=partial(self.attempt_add_materialized_column_index, table, column_names))
                )

        return operations

    def attempt_add_materialized_column_index(self, table: TableWithProperties, column_names: List[str], query_id: str):
        from ee.clickhouse.materialized_columns.columns import create_minmax_index

        already_indexed = self.get_indexed_columns(table)
        to_index = [column_name for column_name in column_names if column_name not in already_indexed]
        if len(to_index) > 0:
            logger.info("Creating minmax index for materialized columns.", table=table, column_names=to_index)
            create_minmax_index(table, to_index)
        else:
            logger.info("Columns already indexed, skipping adding a new index.", table=table, column_names=column_names)
