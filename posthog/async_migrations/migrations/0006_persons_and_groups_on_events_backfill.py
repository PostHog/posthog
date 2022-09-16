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
from posthog.models.instance_setting import get_instance_setting

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

# :KLUDGE: On cloud, groups and person tables now have storage_policy sometimes attached
STORAGE_POLICY_SETTING = lambda: ", storage_policy = 'hot_to_cold'" if settings.CLICKHOUSE_ENABLE_STORAGE_POLICY else ""


class Migration(AsyncMigrationDefinition):
    description = "Backfill persons and groups data on the sharded_events table"

    depends_on = "0005_person_replacing_by_version"

    posthog_min_version = "1.39.0"
    posthog_max_version = "1.40.99"

    parameters = {
        "PERSON_DICT_CACHE_SIZE": (5000000, "ClickHouse cache size (in rows) for persons data.", int),
        "PERSON_DISTINCT_ID_DICT_CACHE_SIZE": (
            5000000,
            "ClickHouse cache size (in rows) for person distinct id data.",
            int,
        ),
        "GROUPS_DICT_CACHE_SIZE": (1000000, "ClickHouse cache size (in rows) for groups data.", int),
        "TIMESTAMP_LOWER_BOUND": ("2020-01-01", "Timestamp lower bound for events to backfill", str),
        "TIMESTAMP_UPPER_BOUND": ("2022-10-01", "Timestamp upper bound for events to backfill", str),
        "TEAM_ID": (
            None,
            "The team_id of team to run backfill for. If unset the backfill will run for all teams.",
            int,
        ),
    }

    def precheck(self):
        # Used to guard against self-hosted users running on `latest` while we make tweaks to the migration
        if not settings.TEST and not get_instance_setting("ALLOW_EXPERIMENTAL_ASYNC_MIGRATIONS"):
            return (False, "ALLOW_EXPERIMENTAL_ASYNC_MIGRATIONS is set to False")
        return analyze_enough_disk_space_free_for_table(EVENTS_DATA_TABLE(), required_ratio=2.0)

    def is_required(self) -> bool:
        rows_not_backfilled_count = sync_execute(
            """
            SELECT count()
            FROM events
            WHERE empty(person_id) OR person_created_at = toDateTime(0)
            """
        )[0][0]

        return rows_not_backfilled_count > 0

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
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.person
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, id)
                    SETTINGS index_granularity = 128 {STORAGE_POLICY_SETTING()}
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2
                    ENGINE = ReplacingMergeTree(version)
                    ORDER BY (team_id, distinct_id)
                    SETTINGS index_granularity = 128
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    CREATE TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}
                    AS {settings.CLICKHOUSE_DATABASE}.groups
                    ENGINE = ReplacingMergeTree(_timestamp)
                    ORDER BY (team_id, group_type_index, group_key)
                    SETTINGS index_granularity = 128 {STORAGE_POLICY_SETTING()}
                """,
                rollback=f"DROP TABLE IF EXISTS {TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.person
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.person_distinct_id2
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}
                    REPLACE PARTITION tuple() FROM {settings.CLICKHOUSE_DATABASE}.groups
                """,
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_person",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_pdi2",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperation(
                fn=lambda query_id: run_optimize_table(
                    unique_name="0006_persons_and_groups_on_events_backfill_groups",
                    query_id=query_id,
                    table_name=f"{settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME}",
                    final=True,
                    deduplicate=True,
                    per_shard=True,
                )
            ),
            AsyncMigrationOperationSQL(
                sql=f"""
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}
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
                    ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}
                    DELETE WHERE is_deleted = 1
                """,
                sql_settings={"mutations_sync": 2},
                rollback=None,
                per_shard=True,
            ),
            AsyncMigrationOperation(fn=self._create_dictionaries, rollback_fn=self._clear_temporary_tables),
            AsyncMigrationOperation(fn=self._run_backfill_mutation),
            AsyncMigrationOperation(fn=self._wait_for_mutation_done),
            AsyncMigrationOperation(fn=self._clear_temporary_tables),
            AsyncMigrationOperation(fn=self._postcheck),
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
                sql=f"ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' MODIFY COLUMN {column} VARCHAR Codec({codec})",
            )

    # TODO: Consider making postcheck a native component of the async migrations spec
    def _postcheck(self, query_id) -> bool:
        incomplete_events_ratio = sync_execute(
            "SELECT countIf(empty(person_id) OR person_created_at = toDateTime(0)) / count() FROM events"
        )[0][0]

        if incomplete_events_ratio > 0.01:
            incomplete_events_percentage = incomplete_events_ratio * 100
            raise Exception(
                f"Backfill did not work succesfully. {int(incomplete_events_percentage)}% of events did not get the correct data."
            )

        # useful for tests
        return True

    def _run_backfill_mutation(self, query_id):
        # If there's an ongoing backfill, skip enqueuing another and jump to the step where we wait for the mutation to finish
        if self._count_running_mutations() > 0:
            return

        team_id = self.get_parameter("TEAM_ID")
        team_id_filter = f" AND team_id = %(team_id)s" if team_id else ""
        where_clause = f"WHERE timestamp > toDateTime(%(timestamp_lower_bound)s) AND timestamp < toDateTime(%(timestamp_upper_bound)s) {team_id_filter}"

        execute_op_clickhouse(
            f"""
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
                {where_clause}
            """,
            {
                "team_id": team_id,
                "timestamp_lower_bound": self.get_parameter("TIMESTAMP_LOWER_BOUND"),
                "timestamp_upper_bound": self.get_parameter("TIMESTAMP_UPPER_BOUND"),
            },
            settings={"max_execution_time": 0},
            per_shard=True,
            query_id=query_id,
        )

    def _create_dictionaries(self, query_id):
        execute_op_clickhouse(
            f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.person_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    id UUID,
                    properties String,
                    created_at DateTime
                )
                PRIMARY KEY team_id, id
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PERSONS_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
            {"cache_size": self.get_parameter("PERSON_DICT_CACHE_SIZE")},
            per_shard=True,
            query_id=query_id,
        ),
        execute_op_clickhouse(
            f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    distinct_id String,
                    person_id UUID
                )
                PRIMARY KEY team_id, distinct_id
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_PDI2_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
            {"cache_size": self.get_parameter("PERSON_DISTINCT_ID_DICT_CACHE_SIZE")},
            per_shard=True,
            query_id=query_id,
        ),
        execute_op_clickhouse(
            f"""
                CREATE DICTIONARY IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}.groups_dict {{on_cluster_clause}}
                (
                    team_id Int64,
                    group_type_index UInt8,
                    group_key String,
                    group_properties String,
                    created_at DateTime
                )
                PRIMARY KEY team_id, group_type_index, group_key
                SOURCE(CLICKHOUSE(TABLE {TEMPORARY_GROUPS_TABLE_NAME} {self._dictionary_connection_string()}))
                LAYOUT(complex_key_cache(size_in_cells %(cache_size)s max_threads_for_updates 6 allow_read_expired_keys 1))
                Lifetime(60000)
            """,
            {"cache_size": self.get_parameter("GROUPS_DICT_CACHE_SIZE")},
            per_shard=True,
            query_id=query_id,
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
            {"cluster": settings.CLICKHOUSE_CLUSTER, "pattern": "%person_properties = dictGetString%"},
        )[0][0]

    def _clear_temporary_tables(self, query_id):
        queries = [
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.person_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.person_distinct_id2_dict {{on_cluster_clause}}",
            f"DROP DICTIONARY IF EXISTS {settings.CLICKHOUSE_DATABASE}.groups_dict {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PERSONS_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_PDI2_TABLE_NAME} {{on_cluster_clause}}",
            f"DROP TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{TEMPORARY_GROUPS_TABLE_NAME} {{on_cluster_clause}}",
        ]
        for query in queries:
            execute_op_clickhouse(query_id=query_id, sql=query, per_shard=True)

    def healthcheck(self):
        result = sync_execute("SELECT free_space FROM system.disks")
        # 100mb or less left
        if int(result[0][0]) < 100000000:
            return (False, "ClickHouse available storage below 100MB")

        return (True, None)
