from functools import cached_property

import structlog

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
    AsyncMigrationType,
)
from posthog.async_migrations.utils import execute_op_clickhouse, run_optimize_table
from posthog.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.settings import CLICKHOUSE_DATABASE

logger = structlog.get_logger(__name__)

"""
Migration summary
=================

Backfill the sharded_events table to add data for the following columns:

- person_id
- person_properties
- person_created_at
- group_X_properties
- group_X_created_at

This allows us to switch entirely to only querying the events table for insights,
without having to hit additional tables for persons, groups, and distinct IDs.

Migration strategy
==================

We will run the following operations on the cluster
(or on one node per shard if shard-level configuration is provided):

1. Create temporary tables with the relevant columns from `person`, `person_distinct_id`, and `groups`
2. Insert data from the main tables into them
3. Optimize the temporary tables to remove duplicates
4. Create a dictionary to query each temporary table
5. Run an ALTER TABLE ... UPDATE to backfill all the data using the dictionaries
"""

TEMPORARY_PERSONS_TABLE_NAME = "tmp_person_0006"
TEMPORARY_PDI2_TABLE_NAME = "tmp_person_distinct_id2_0006"
TEMPORARY_GROUPS_TABLE_NAME = "tmp_groups_0006"


class Migration(AsyncMigrationDefinition):
    description = "Backfill persons and groups data on the sharded_events table"

    depends_on = "0005_person_replacing_by_version"

    def precheck(self):
        return True, None

    def is_required(self) -> bool:
        rows = sync_execute(
            """
            SELECT comment
            FROM system.columns
            WHERE database = %(database)s AND
            table = %(events_data_table)s
        """,
            {"database": CLICKHOUSE_DATABASE, "events_data_table": EVENTS_DATA_TABLE()},
        )

        comments = [row[0] for row in rows]
        return "skip_0006_persons_and_groups_on_events_backfill" not in comments

    @cached_property
    def operations(self):
        return [
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}} AS person
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}} AS person_distinct_id2
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, distinct_id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}} AS groups
                    ENGINE = ReplacingMergeTree(_timestamp)
                    ORDER BY (team_id, group_type_index, group_key)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM person
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM person_distinct_id2
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM groups
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_person",
                    query_id=query_id,
                    table_name=TEMPORARY_PERSONS_TABLE_NAME,
                    final=True,
                    deduplicate=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_pdi2",
                    query_id=query_id,
                    table_name=TEMPORARY_PDI2_TABLE_NAME,
                    final=True,
                    deduplicate=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_groups",
                    query_id=query_id,
                    table_name=TEMPORARY_GROUPS_TABLE_NAME,
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE DICTIONARY IF NOT EXISTS person_dict {{on_cluster_clause}}
                    (
                        team_id Int64,
                        id UUID,
                        properties String,
                        created_at DateTime
                    )
                    PRIMARY KEY team_id, id
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PERSONS_TABLE_NAME} DB '{CLICKHOUSE_DATABASE}'))
                    LAYOUT(complex_key_cache(size_in_cells 5000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback="DROP DICTIONARY IF EXISTS person_dict {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE DICTIONARY IF NOT EXISTS person_distinct_id2_dict {{on_cluster_clause}}
                    (
                        team_id Int64,
                        distinct_id String,
                        person_id UUID
                    )
                    PRIMARY KEY team_id, distinct_id
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PDI2_TABLE_NAME} DB '{CLICKHOUSE_DATABASE}'))
                    LAYOUT(complex_key_cache(size_in_cells 50000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback="DROP DICTIONARY IF EXISTS person_distinct_id2_dict {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE DICTIONARY IF NOT EXISTS groups_dict {{on_cluster_clause}}
                    (
                        team_id Int64,
                        group_type_index UInt8,
                        group_key String,
                        group_properties String,
                        created_at DateTime
                    )
                    PRIMARY KEY team_id, group_type_index, group_key
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_GROUPS_TABLE_NAME} DB '{CLICKHOUSE_DATABASE}'))
                    LAYOUT(complex_key_cache(size_in_cells 1000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback="DROP DICTIONARY IF EXISTS groups_dict {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperation(fn=self.run_backfill,),
        ]

    def run_backfill(self, query_id):
        # :TODO: Make this work when executing per shard
        execute_op_clickhouse(
            query_id=query_id,
            sql=f"""
                ALTER TABLE {EVENTS_DATA_TABLE()}
                UPDATE
                    person_id=toUUID(dictGet('person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id))),
                    person_properties=dictGetString('person_dict', 'properties', tuple(team_id, toUUID(dictGet('person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id))))),
                    person_created_at=dictGetDateTime('person_dict', 'created_at', tuple(team_id, toUUID(dictGet('person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id))))),
                    group0_properties=dictGetString('groups_dict', 'group_properties', tuple(team_id, 0, $group_0)),
                    group1_properties=dictGetString('groups_dict', 'group_properties', tuple(team_id, 1, $group_1)),
                    group2_properties=dictGetString('groups_dict', 'group_properties', tuple(team_id, 2, $group_2)),
                    group3_properties=dictGetString('groups_dict', 'group_properties', tuple(team_id, 3, $group_3)),
                    group4_properties=dictGetString('groups_dict', 'group_properties', tuple(team_id, 4, $group_4)),
                    group0_created_at=dictGetDateTime('groups_dict', 'created_at', tuple(team_id, 0, $group_0)),
                    group1_created_at=dictGetDateTime('groups_dict', 'created_at', tuple(team_id, 1, $group_1)),
                    group2_created_at=dictGetDateTime('groups_dict', 'created_at', tuple(team_id, 2, $group_2)),
                    group3_created_at=dictGetDateTime('groups_dict', 'created_at', tuple(team_id, 3, $group_3)),
                    group4_created_at=dictGetDateTime('groups_dict', 'created_at', tuple(team_id, 4, $group_4))
                WHERE person_id <> toUUIDOrZero('')
            """,
            settings={"mutations_sync": 1, "max_execution_time": 0},
        )

    def progress(self, migration_instance: AsyncMigrationType) -> int:
        # Use parts_to_do when running the backfill as a proxy
        return 1
