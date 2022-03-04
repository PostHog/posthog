import re
from dataclasses import dataclass
from functools import cached_property
from typing import List, Optional

import structlog
from constance import config
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.table_engines import MergeTreeEngine
from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation

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
        c. using `ALTER TABLE ATTACH/DROP PARTITIONS` to move data to the new table.
        d. rename tables
        e. re-enabling ingestion

We use ATTACH/DROP tables to do the table migration instead of a normal INSERT. This method allows
moving data without increasing disk usage between identical schemas.

`events` and `session_recording_events` require extra steps as they're also sharded:

    1. The new table should be named `sharded_TABLENAME`
    2. Create `TABLENAME` and `writable_TABLENAME` tables which are responsible for distributed reads and writes
    3. Update materialized views to write to `writable_TABLENAME`

Constraints:

    1. This migration relies on there being exactly one ClickHouse node when it's run.
    2. For person and events tables, the schema tries to preserve any materialized columns.
    3. This migration requires there to be no ongoing part merges while it's executing.
    4. This migration depends on 0002_events_sample_by. If it didn't, this could be a normal migration.
    5. This migration depends on the person_distinct_id2 async migration to have completed.
"""


@dataclass(frozen=True)
class TableMigrationData:
    name: str
    new_table_engine: MergeTreeEngine
    materialized_view_name: Optional[str]
    create_materialized_view: Optional[str]

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
    extra_tables: List[str]

    @property
    def renamed_table_name(self):
        return self.rename_to


class Migration(AsyncMigrationDefinition):

    description = "Replace tables with replicated counterparts"

    depends_on = "0003_fill_person_distinct_id2"

    def is_required(self):
        return "Distributed" not in self.get_current_engine("events")

    def precheck(self):
        if not settings.CLICKHOUSE_REPLICATION:
            return False, "CLICKHOUSE_REPLICATION env var needs to be set for this migration"

        number_of_nodes = self.get_number_of_nodes_in_cluster()
        if number_of_nodes > 1:
            return (
                False,
                f"ClickHouse cluster should only contain one node at the time of this migration, found {number_of_nodes}",
            )

        return True, None

    @cached_property
    def operations(self):
        TABLE_MIGRATION_OPERATIONS = [
            operation for table in self.tables_to_migrate() for operation in self.replicated_table_operations(table)
        ]

        return [
            AsyncMigrationOperation.simple_op(sql="SYSTEM STOP MERGES", rollback="SYSTEM START MERGES"),
            AsyncMigrationOperation(
                fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
                rollback_fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
            ),
            *TABLE_MIGRATION_OPERATIONS,
            AsyncMigrationOperation(
                fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", False),
                rollback_fn=lambda _: setattr(config, "COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True),
            ),
            AsyncMigrationOperation.simple_op(sql="SYSTEM START MERGES", rollback="SYSTEM STOP MERGES",),
        ]

    def replicated_table_operations(self, table: TableMigrationData):
        yield AsyncMigrationOperation.simple_op(
            sql=f"""
            CREATE TABLE {table.tmp_table_name} AS {table.name}
            ENGINE = {self.get_new_engine(table)}
            """,
            rollback=f"DROP TABLE IF EXISTS {table.tmp_table_name}",
        )

        if table.materialized_view_name is not None:
            yield AsyncMigrationOperation.simple_op(
                sql=f"DROP TABLE IF EXISTS {table.materialized_view_name}", rollback=table.create_materialized_view,
            )

        yield AsyncMigrationOperation(
            fn=lambda _: self.move_partitions(table.name, table.tmp_table_name),
            rollback_fn=lambda _: self.move_partitions(table.tmp_table_name, table.name),
        )

        yield AsyncMigrationOperation(
            fn=lambda _: self.rename_tables(
                table.name, table.tmp_table_name, table.renamed_table_name, table.backup_table_name
            ),
            rollback_fn=lambda _: self.rename_tables(
                table.backup_table_name,
                table.renamed_table_name,
                table.tmp_table_name,
                table.name,
                skip_if_backup_exists=True,
            ),
        )

        if table.materialized_view_name is not None:
            yield AsyncMigrationOperation.simple_op(
                sql=table.create_materialized_view, rollback=f"DROP TABLE IF EXISTS {table.materialized_view_name}",
            )

        # NOTE: Relies on IF NOT EXISTS on the query
        if isinstance(table, ShardedTableMigrationData):
            for create_table_query in table.extra_tables:
                yield AsyncMigrationOperation.simple_op(sql=create_table_query)

    def get_current_engine(self, table_name: str) -> Optional[str]:
        result = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
            {"database": settings.CLICKHOUSE_DATABASE, "name": table_name},
        )

        return result[0][0] if len(result) > 0 else None

    def get_new_engine(self, table: TableMigrationData):
        """
        Returns new table engine statement for the table.

        Note that the engine statement also includes PARTITION BY, ORDER BY, SAMPLE BY and SETTINGS,
        so we use the current table as a base for that and only replace the
        """
        current_engine = self.get_current_engine(table.name)

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

        running_merges = sync_execute(
            "SELECT count() FROM system.merges WHERE database = %(database)s AND table = %(table)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table": from_table},
        )[0][0]

        assert (
            running_merges == 0
        ), f"No merges should be running on tables while partitions are being moved. table={from_table}"

        partitions = sync_execute(
            "SELECT DISTINCT partition FROM system.parts WHERE database = %(database)s AND table = %(table)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table": from_table},
        )

        for (partition,) in partitions:
            logger.info("Moving partitions between tables", from_table=from_table, to_table=to_table, id=partition)
            # :KLUDGE: Partition IDs are special and cannot be passed as arguments
            sync_execute(f"ALTER TABLE {to_table} ATTACH PARTITION {partition} FROM {from_table}")
            sync_execute(f"ALTER TABLE {from_table} DROP PARTITION {partition}")

    def rename_tables(
        self, data_table_name, tmp_table_name, new_main_table_name, backup_table_name, skip_if_backup_exists=False
    ):
        # :KLUDGE: Due to how async migrations rollback works, we need to check whether backup table exists even if the rename failed
        #   in the first place
        if skip_if_backup_exists and self.get_current_engine(backup_table_name) is not None:
            logger.info(
                "Backup table already exists, skipping renaming.",
                data_table_name=data_table_name,
                new_table_name=tmp_table_name,
                new_main_table_name=new_main_table_name,
                backup_table_name=backup_table_name,
            )
            return

        return sync_execute(
            f"RENAME TABLE {data_table_name} TO {backup_table_name}, {tmp_table_name} TO {new_main_table_name}"
        )

    def get_number_of_nodes_in_cluster(self):
        return sync_execute(
            "SELECT count() FROM clusterAllReplicas(%(cluster)s, system, one)", {"cluster": settings.CLICKHOUSE_CLUSTER}
        )[0][0]

    def tables_to_migrate(self):
        from ee.clickhouse.sql.cohort import COHORTPEOPLE_TABLE_ENGINE
        from ee.clickhouse.sql.dead_letter_queue import DEAD_LETTER_QUEUE_TABLE_ENGINE, DEAD_LETTER_QUEUE_TABLE_MV_SQL
        from ee.clickhouse.sql.events import (
            DISTRIBUTED_EVENTS_TABLE_SQL,
            EVENTS_DATA_TABLE_ENGINE,
            EVENTS_TABLE_MV_SQL,
            WRITABLE_EVENTS_TABLE_SQL,
        )
        from ee.clickhouse.sql.groups import GROUPS_TABLE_ENGINE, GROUPS_TABLE_MV_SQL
        from ee.clickhouse.sql.person import (
            PERSON_DISTINCT_ID2_MV_SQL,
            PERSON_DISTINCT_ID2_TABLE_ENGINE,
            PERSON_STATIC_COHORT_TABLE_ENGINE,
            PERSONS_TABLE_ENGINE,
            PERSONS_TABLE_MV_SQL,
        )
        from ee.clickhouse.sql.plugin_log_entries import (
            PLUGIN_LOG_ENTRIES_TABLE_ENGINE,
            PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
        )
        from ee.clickhouse.sql.session_recording_events import (
            DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
            SESSION_RECORDING_EVENTS_DATA_TABLE_ENGINE,
            SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
            WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
        )

        return [
            ShardedTableMigrationData(
                name="events",
                new_table_engine=EVENTS_DATA_TABLE_ENGINE(),
                materialized_view_name="events_mv",
                rename_to="sharded_events",
                create_materialized_view=EVENTS_TABLE_MV_SQL(),
                extra_tables=[WRITABLE_EVENTS_TABLE_SQL(), DISTRIBUTED_EVENTS_TABLE_SQL()],
            ),
            ShardedTableMigrationData(
                name="session_recording_events",
                new_table_engine=SESSION_RECORDING_EVENTS_DATA_TABLE_ENGINE(),
                materialized_view_name="session_recording_events_mv",
                rename_to="sharded_session_recording_events",
                create_materialized_view=SESSION_RECORDING_EVENTS_TABLE_MV_SQL(),
                extra_tables=[
                    WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
                ],
            ),
            TableMigrationData(
                name="events_dead_letter_queue",
                new_table_engine=DEAD_LETTER_QUEUE_TABLE_ENGINE(),
                materialized_view_name="events_dead_letter_queue_mv",
                create_materialized_view=DEAD_LETTER_QUEUE_TABLE_MV_SQL,
            ),
            TableMigrationData(
                name="groups",
                new_table_engine=GROUPS_TABLE_ENGINE(),
                materialized_view_name="groups_mv",
                create_materialized_view=GROUPS_TABLE_MV_SQL,
            ),
            TableMigrationData(
                name="person",
                new_table_engine=PERSONS_TABLE_ENGINE(),
                materialized_view_name="person_mv",
                create_materialized_view=PERSONS_TABLE_MV_SQL,
            ),
            TableMigrationData(
                name="person_distinct_id2",
                new_table_engine=PERSON_DISTINCT_ID2_TABLE_ENGINE(),
                materialized_view_name="person_distinct_id2_mv",
                create_materialized_view=PERSON_DISTINCT_ID2_MV_SQL,
            ),
            TableMigrationData(
                name="plugin_log_entries",
                new_table_engine=PLUGIN_LOG_ENTRIES_TABLE_ENGINE(),
                materialized_view_name="plugin_log_entries_mv",
                create_materialized_view=PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
            ),
            TableMigrationData(
                name="cohortpeople",
                new_table_engine=COHORTPEOPLE_TABLE_ENGINE(),
                materialized_view_name=None,
                create_materialized_view=None,
            ),
            TableMigrationData(
                name="person_static_cohort",
                new_table_engine=PERSON_STATIC_COHORT_TABLE_ENGINE(),
                materialized_view_name=None,
                create_materialized_view=None,
            ),
        ]
