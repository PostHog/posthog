import re
from dataclasses import dataclass
from functools import cached_property

import structlog

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.person import PERSONS_TABLE_ENGINE
from ee.clickhouse.sql.table_engines import MergeTreeEngine
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.settings import CLICKHOUSE_DATABASE

logger = structlog.get_logger(__name__)

"""
Migration summary:

Schema change to migrate tables to support replication and more than
one shard.

This allows for higher scalability as more hosts can be added under ClickHouse.

The migration strategy:

    1. We have a list of tables that might need replacing below.
    2. For each one, we replace the current engine with the appropriate Replicated by:
        a. creating a new table with the right engine and identical schema
        b. temporarily stopping ingestion to the table
        c. using `ALTER TABLE MOVE PARTITIONS` to move data to the new table
        d. rename tables
        e. re-enabling ingestion

`events` and `session_recording_events` require extra steps as they're also sharded:

    1. The new table should be named `sharded_TABLENAME`
    2. Create `TABLENAME` and `writable_TABLENAME` tables which are responsible for distributed reads and writes
    3. Update materialized views to write to `writable_TABLENAME`

Constraints:

    1. This migration relies on there being exactly one node when it's run.
    2. For person and events tables, the schema tries to preserve any materialized columns.
    3. This migration hard depends on 0002_events_sample_by. If it didn't, this could be a normal migration.
"""


@dataclass(frozen=True)
class TableMigrationData:
    name: str
    new_table_engine: MergeTreeEngine
    materialized_view_name: str

    @property
    def renamed_table_name(self):
        return self.name

    @property
    def backup_table_name(self):
        return f"{self.name}_backup_0004_replicated_schema"

    @property
    def tmp_table_name(self):
        return f"{self.name}_tmp_0004_replicated_schema"


@dataclass(frozen=True)
class ShardedTableMigrationData(TableMigrationData):
    rename_to: str
    create_materialized_view: str

    @property
    def renamed_table_name(self):
        return self.rename_to


TABLES_TO_MIGRATE = [
    TableMigrationData(name="person", new_table_engine=PERSONS_TABLE_ENGINE, materialized_view_name="person_mv"),
]


class Migration(AsyncMigrationDefinition):

    description = "Replace tables with replicated counterparts"

    depends_on = "0002_events_sample_by"

    def is_required(self):
        # :TODO: Check whether events table is Distributed
        return True

    @cached_property
    def operations(self):
        # :TODO: Validate CLICKHOUSE_REPLICATED is set
        # :TODO: Validate only a single replica (this one)
        # :TODO: Stop column materialization
        # :TODO: Assert no ongoing merges
        # :TODO: Stop merges for that part.
        return [operation for table in TABLES_TO_MIGRATE for operation in self.replicated_table_operations(table)]

    def replicated_table_operations(self, table: TableMigrationData):
        return [
            AsyncMigrationOperation.simple_op(
                sql=f"""
                CREATE TABLE {table.tmp_table_name} AS {table.name}
                ENGINE = {self.get_new_engine(table)}
                """,
                rollback=f"DROP TABLE {table.tmp_table_name}",
            ),
            # AsyncMigrationOperation.simple_op(
            #     sql=f"DETACH TABLE {table.materialized_view_name}",
            #     rollback=f"ATTACH TABLE {table.materialized_view_name}",
            # ),
            AsyncMigrationOperation(
                fn=lambda _: self.move_partitions(table.name, table.tmp_table_name),
                rollback_fn=lambda _: self.move_partitions(table.tmp_table_name, table.name),
            ),
            # AsyncMigrationOperation.simple_op(
            #     sql=f"RENAME TABLE {table.name} TO {table.backup_table_name}, {table.tmp_table_name} TO {table.renamed_table_name}",
            #     rollback=f"RENAME TABLE {table.backup_table_name} TO {table.name}, {table.renamed_table_name} TO {table.tmp_table_name}",
            # ),
            # AsyncMigrationOperation.simple_op(
            #     sql=f"DETACH TABLE {table.materialized_view_name}",
            #     rollback=f"ATTACH TABLE {table.materialized_view_name}",
            # ),
        ]

    def get_new_engine(self, table: TableMigrationData):
        """
        Returns new table engine statement for the table.

        Note that the engine statement also includes PARTITION BY, ORDER BY, SAMPLE BY and SETTINGS,
        so we use the current table as a base for that and only replace the
        """
        current_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": CLICKHOUSE_DATABASE, "name": table.name},
        )[0][0]

        if "Replicated" in current_engine or "Distributed" in current_engine:
            raise ValueError(
                f"""
                Table engine of incorrect type, cannot be replicated or distributed.

                table={table.name}, current_engine={current_engine}
            """
            )

        # Remove the current engine from the string
        return re.sub(r".*MergeTree\(\w+\)", str(table.new_table_engine), current_engine)

    def move_partitions(self, from_table: str, to_table: str):
        """
        This step the new table with old tables data without using any extra space.

        `ATTACH PARTITION` uses hard links for the copy, so as long as the two datasets are equal everything is good.

        Constraints:
        1. Identical schemas between the two schemas
        2. Merges and ingestion are stopped on the table
        3. We can't use MOVE PARTITION due to validation errors due to differing table engines
        """

        partitions = sync_execute(
            "SELECT DISTINCT partition FROM system.parts WHERE database = %(database)s AND table = %(table)s",
            {"database": CLICKHOUSE_DATABASE, "table": from_table},
        )

        for (partition,) in partitions:
            logger.info("Moving partitions between tables", from_table=from_table, to_table=to_table, id=partition)
            # :KLUDGE: Partition IDs are special and cannot be passed as arguments
            sync_execute(f"ALTER TABLE {to_table} ATTACH PARTITION {partition} FROM {from_table}")
            sync_execute(f"ALTER TABLE {from_table} DROP PARTITION {partition}")
