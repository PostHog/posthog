from functools import cached_property

import structlog
from django.conf import settings

from posthog.async_migrations.definition import (
    AsyncMigrationDefinition,
    AsyncMigrationOperation,
    AsyncMigrationOperationSQL,
)
from posthog.async_migrations.disk_util import analyze_enough_disk_space_free_for_table
from posthog.async_migrations.utils import execute_op_clickhouse, run_optimize_table, sleep_until_finished
from posthog.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE

logger = structlog.get_logger(__name__)

"""
Migration summary
=================

Backfill the sharded_events table to add data for the following columns:

- person_id
- person_properties
- person_created_at
- groupX_properties
- groupX_created_at

This allows us to switch entirely to only querying the events table for insights,
without having to hit additional tables for persons, groups, and distinct IDs.

Migration strategy
==================

We will run the following operations on the cluster
(or on one node per shard if shard-level configuration is provided):

1. Update `person_properties` and `groupX_properties` columns to use ZSTD(3) compression
2. Create temporary tables with the relevant columns from `person`, `person_distinct_id`, and `groups`
3. Copy data from the main tables into them
4. Optimize the temporary tables to remove duplicates and remove deleted data
5. Create a dictionary to query each temporary table with caching
6. Run an ALTER TABLE ... UPDATE to backfill all the data using the dictionaries

Constraints
===========

1. The migration requires a lot of extra space for the new columns. At least 2x disk space is required to avoid issues while migrating.
2. We use ZSTD(3) compression on the new columns to save on space and speed up large reads.
3. New columns need to be populated for new rows before running this async migration.
"""

TEMPORARY_PERSONS_TABLE_NAME = "tmp_person_0006"
TEMPORARY_PDI2_TABLE_NAME = "tmp_person_distinct_id2_0006"
TEMPORARY_GROUPS_TABLE_NAME = "tmp_groups_0006"


class Migration(AsyncMigrationDefinition):
    description = "Backfill persons and groups data on the sharded_events table"

    depends_on = "0005_person_replacing_by_version"

    def precheck(self):
        if not settings.MULTI_TENANCY:
            return False, "This async migration is not yet ready for self-hosted users"

        return analyze_enough_disk_space_free_for_table(EVENTS_DATA_TABLE(), required_ratio=2.0)

    def is_required(self) -> bool:
        compression_codec = sync_execute(
            """
            SELECT compression_codec
            FROM system.columns
            WHERE database = %(database)s
              AND table = %(events_data_table)s
              AND name = 'person_properties'
        """,
            {"database": settings.CLICKHOUSE_DATABASE, "events_data_table": EVENTS_DATA_TABLE()},
        )[0][0]

        return compression_codec != "CODEC(ZSTD(3))"

    @cached_property
    def operations(self):
        return [
            AsyncMigrationOperation(
                # See https://github.com/PostHog/posthog/issues/10616 for details on choice of codec
                fn=lambda query_id: self._update_properties_column_compression_codec(query_id, "ZSTD(3)"),
                rollback_fn=lambda query_id: self._update_properties_column_compression_codec(query_id, "LZ4"),
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}} AS {settings.CLICKHOUSE_DATABASE}.person
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}} AS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, distinct_id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}} AS {settings.CLICKHOUSE_DATABASE}.groups
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
                    ALTER TABLE {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    DELETE WHERE is_deleted = 1 OR person_id IN (
                        SELECT id FROM {TEMPORARY_PERSONS_TABLE_NAME} WHERE is_deleted=1
                    )
                """,
                sql_settings={"mutations_sync": 2},
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    DELETE WHERE is_deleted = 1
                """,
                sql_settings={"mutations_sync": 2},
                rollback=None,
                per_shard=True,
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
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PERSONS_TABLE_NAME} {self._dictionary_connection_string()}))
                    LAYOUT(complex_key_cache(size_in_cells 5000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback=f"DROP DICTIONARY IF EXISTS person_dict {{on_cluster_clause}}",
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
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PDI2_TABLE_NAME} {self._dictionary_connection_string()}))
                    LAYOUT(complex_key_cache(size_in_cells 50000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback=f"DROP DICTIONARY IF EXISTS person_distinct_id2_dict {{on_cluster_clause}}",
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
                    SOURCE(CLICKHOUSE(TABLE {TEMPORARY_GROUPS_TABLE_NAME} {self._dictionary_connection_string()}))
                    LAYOUT(complex_key_cache(size_in_cells 1000000 max_threads_for_updates 6 allow_read_expired_keys 1))
                    Lifetime(60000)
                """,
                rollback=f"DROP DICTIONARY IF EXISTS groups_dict {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {EVENTS_DATA_TABLE()}
                    {{on_cluster_clause}}
                    UPDATE
                        person_id = toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id))),
                        person_properties = dictGetString(
                            '{settings.CLICKHOUSE_DATABASE}.person_dict',
                            'properties',
                            tuple(
                                team_id,
                                toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id)))
                            )
                        ),
                        person_created_at = dictGetDateTime(
                            '{settings.CLICKHOUSE_DATABASE}.person_dict',
                            'created_at',
                            tuple(
                                team_id,
                                toUUID(dictGet('{settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict', 'person_id', tuple(team_id, distinct_id)))
                            )
                        ),
                        group0_properties = dictGetString('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 0, $group_0)),
                        group1_properties = dictGetString('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 1, $group_1)),
                        group2_properties = dictGetString('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 2, $group_2)),
                        group3_properties = dictGetString('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 3, $group_3)),
                        group4_properties = dictGetString('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'group_properties', tuple(team_id, 4, $group_4)),
                        group0_created_at = dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 0, $group_0)),
                        group1_created_at = dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 1, $group_1)),
                        group2_created_at = dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 2, $group_2)),
                        group3_created_at = dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 3, $group_3)),
                        group4_created_at = dictGetDateTime('{settings.CLICKHOUSE_DATABASE}.groups_dict', 'created_at', tuple(team_id, 4, $group_4))
                    WHERE person_id = toUUIDOrZero('')
                """,
                sql_settings={"max_execution_time": 0},
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(fn=self._wait_for_mutation_done,),
            AsyncMigrationOperation(fn=self._clear_temporary_tables),
        ]

    def _dictionary_connection_string(self):
        result = f"DB '{settings.CLICKHOUSE_DATABASE}'"
        if settings.CLICKHOUSE_USER:
            result += f" USER '{settings.CLICKHOUSE_USER}'"
        if settings.CLICKHOUSE_PASSWORD:
            result += f" PASSWORD '{settings.CLICKHOUSE_PASSWORD}'"
        return result

    def _update_properties_column_compression_codec(self, query_id, codec):
        columns = [
            "person_properties",
            "group0_properties",
            "group1_properties",
            "group2_properties",
            "group3_properties",
            "group4_properties",
        ]
        for column in columns:
            execute_op_clickhouse(
                query_id=query_id,
                sql=f"ALTER TABLE {EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY COLUMN {column} VARCHAR Codec({codec})",
            )

    def _wait_for_mutation_done(self, query_id):
        # :KLUDGE: mutations_sync does not work with ON CLUSTER queries, causing race conditions with subsequent steps
        sleep_until_finished("events table backill", lambda: self._count_running_mutations() > 0)

    def _count_running_mutations(self):
        return sync_execute(
            """
            SELECT count()
            FROM clusterAllReplicas(%(cluster)s, system, 'mutations')
            WHERE not is_done AND command LIKE %(pattern)s
            """,
            {"cluster": settings.CLICKHOUSE_CLUSTER, "pattern": "%person_properties = dictGetString%",},
        )[0][0]

    def _clear_temporary_tables(self, query_id):
        queries = [
            f"DROP DICTIONARY IF EXISTS person_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS person_distinct_id2_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS groups_dict {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
        ]
        for query in queries:
            execute_op_clickhouse(query_id=query_id, sql=query, per_shard=True)

    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)
